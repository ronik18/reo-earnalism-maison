# Maison CDN, payload and offline delivery contract

Version 1.0.0 · 17 November 2026 · proposed implementation specification, not a deployed configuration. This companion to LLD.md, api-contracts.md, openapi.yaml and database.sql covers the delivery boundary for S01–S26. `cache-policy.json` holds machine-readable policy values; `payload-examples.json` contains inert examples; `screen-contract-matrix.csv` maps every screen. OpenAPI owns HTTP schemas and operation names. Resolve any disagreement before implementing the affected flow.

## 1. Delivery topology and trust

Keep one Django application on Render Singapore (2–6 instances), PostgreSQL 17 on Neon Scale Singapore (0.5–2 CU, warm, autosuspend disabled), public assets on Cloudflare CDN with an R2 custom domain, private Reader/audio on the R2 S3 endpoint, and approved video on Stream. No Redis, private CDN proxy, always-running queue worker, second frontend server or additional paid caching service is required. The existing scheduled Django maintenance command processes PostgreSQL outbox work.

Cloudflare may cache only explicitly admitted anonymous HTML, catalog JSON, reviewed covers, bounded free previews and fingerprinted build assets. All account, entitlement, payment, staff and signed-grant responses are private/no-store. An anonymous public page must not initialize a session or set a CSRF cookie. Obtain session/CSRF state from the private session endpoint before an account mutation. A request containing any Cookie or Authorization header bypasses shared cache, even on a public path. Thus `/{locale}/` can render S03 anonymously and S04 privately without sharing member data. A member's Continue shelf comes from `/api/v1/me/vault`; public `/api/v1/home` never includes it.

R2 presigned URLs are bearer capabilities for the S3 endpoint; Cloudflare explicitly does not support them on custom domains. Do not rewrite a signed S3 URL to the public assets host or claim those paid bytes use this site's CDN cache. Public custom-domain delivery and private S3 delivery are distinct paths. Keep `r2.dev` disabled for private storage. [R2 presigned URLs](https://developers.cloudflare.com/r2/api/s3/presigned-urls/), [R2 public buckets](https://developers.cloudflare.com/r2/buckets/public-buckets/).

Every grant checks the current session/device, live exact edition revision, released format, rights territory/time/action and entitlement in PostgreSQL. An untrusted locale, territory query, cached membership flag or signed-in UI never authorizes an object. The trusted edge country header is replaced at the edge and validated at the origin. Unknown territory fails a restricted grant. No protected bytes or internal rights/source evidence go into public SSR bootstrap, public serializer, search record or analytics.

## 2. Canonical cache keys

Use the default full URL cache key: scheme, allowed host, normalized path and complete canonical query. Do not introduce custom per-user cache keys. For catalog JSON use `?locale=en&territory=IN` in that order. SSR embeds locale in the path and uses `?territory=IN` where territory changes discovery. Only `en` and `bn` and validated uppercase ISO country codes are accepted. A bare locale route receives an uncached canonical redirect to an explicit storefront territory; the final cached response does not vary invisibly by IP. Territory is discovery context; grants still perform their own rights check.

The first unfiltered page of named collections/home/title/series/track metadata is eligible. Search, filter combinations, cursor pages, suggestions, content manifests, timing maps and all unrecognized query variants bypass cache. Reject duplicate/unknown parameters with 400, or redirect with no-store to a canonical representation. Never ignore query strings. This bounds both key cardinality and the set of listing URLs that publication must purge. `/api/v1/search` has private/no-store headers even for anonymous requests; do not log raw search text by default.

Public catalog responses contain no prices, currency conversions, saved state, progress, entitlements, access decisions or personalized recommendation ordering. Fetch authenticated `/commerce/offers` for actual price/currency/renewal terms; those responses are never shared. A public title may describe released formats and the existence of a preview, not whether this member owns it. Do not vary cached bytes by Accept-Language, theme, user agent, device size, arbitrary Origin or forwarded headers. Responsive CSS and local theme preference produce the same source bytes. `Content-Language` describes those bytes; `Vary: Accept-Encoding` is sufficient for encoding. Cloudflare does not make arbitrary Vary values into safe custom keys automatically. [Origin Cache Control](https://developers.cloudflare.com/cache/concepts/cache-control/).

Example independent keys:

```
https://app.example.invalid/api/v1/home?locale=en&territory=IN
https://app.example.invalid/api/v1/home?locale=bn&territory=IN
https://app.example.invalid/en/titles/example-story?territory=IN
https://assets.example.invalid/covers/{sha256}/w480.webp
```

The example hosts are placeholders, not provisioned domains. Never put email, session ID, user ID or a bearer URL in a cache key, browser history, referrer, error report or analytics event.

## 3. Header and TTL contract

All values below are initial engineering bounds, not measured performance claims. The policy JSON is the numeric source of truth. Cloudflare requires an explicit cache eligibility rule for HTML/JSON; headers alone do not admit every MIME type. Respect Origin Cache Control, disable Always Online, retain Cache Deception Armor, and do not configure an Edge TTL override that ignores private/no-store or strips Set-Cookie. The private bypass rule must win over public eligibility. Existing access controls are not replaced by cache rules.

| Response class | Browser TTL | Edge TTL | SWR / stale-if-error | Rule |
|---|---:|---:|---:|---|
| Anonymous catalog HTML / admitted JSON | 0 s, revalidate | 30 s | 0 / 0 | Rights-sensitive discovery; no stale fallback |
| Noncatalog editorial/help HTML | 0 s, revalidate | 300 s | 30 / 300 s | Only content without rights/access state |
| Physically bounded public previews | 0 s, revalidate | 60 s | 0 / 0 | Current preview policy validated at origin |
| Hashed public covers | 300 s | 3,600 s | 0 / 0 | Known immutable rendition paths; purge on withdrawal |
| Hashed JS/CSS/fonts/logo | 31,536,000 s | 31,536,000 s | none | Immutable bytes; new build uses new paths |
| SW script / web manifest / version pointer | 0 s, revalidate | bypass | none | Never immutable current pointer |
| Auth/me/commerce/staff/search/manifests/grants | no-store | bypass | none | Includes all success/error/conditional statuses |
| Private R2 paid objects | no-store | no app CDN | none | Short-lived S3 capability |
| Stream | provider controlled | no app CDN proxy | provider controlled | Only grant response is governed here |

For an eligible anonymous catalog response:

```http
HTTP/1.1 200 OK
Content-Type: application/json; charset=utf-8
Content-Language: bn
Cache-Control: public, max-age=0, must-revalidate
Cloudflare-CDN-Cache-Control: public, max-age=30, stale-while-revalidate=0, stale-if-error=0
Vary: Accept-Encoding
ETag: W/"catalog-v1-bn-IN-17"
X-Content-Type-Options: nosniff
```

For noncatalog editorial HTML the Cloudflare-specific header instead contains `public, max-age=300, stale-while-revalidate=30, stale-if-error=300`. Separate edge and browser headers deliberately. Do not add `s-maxage` casually: the provider's documented revalidation behavior can defeat the intended SWR policy. Cloudflare-CDN-Cache-Control takes precedence at that edge; do not accidentally override it with a cache response rule. [CDN-Cache-Control](https://developers.cloudflare.com/cache/concepts/cdn-cache-control/).

For **every** private response, including 200, 206, 304, 401, 403, 404, 409, 410, 412, 429 and 5xx:

```http
Cache-Control: private, no-store, max-age=0
CDN-Cache-Control: no-store
Cloudflare-CDN-Cache-Control: no-store
Pragma: no-cache
Vary: Cookie, Authorization
Referrer-Policy: strict-origin-when-cross-origin
```

Set those headers after exception serialization as well as normal views. Any Set-Cookie response receives the private policy and is ineligible for shared cache. Never cache an error because its URL resembles a static file. Authenticate and check current rights **before** If-None-Match/If-Modified-Since evaluation: denied access returns 403/410, never a 304 that tells the browser to reuse protected content. If an authorized conditional response is deliberately emitted, its 304 carries private/no-store too. Range handling does not weaken this rule. A public revalidation response repeats its cache class and validators; it never inherits a previous private class.

Use weak representation ETags for public compressed JSON unless a strong tag truly hashes the selected encoded representation. An R2 ETag is a provider object validator, not a promise of SHA-256. Download integrity uses explicit publication hashes and lengths. Do not install global heuristic caching or cached error pages.

## 4. Payload boundaries, versions and budgets

All JSON is UTF-8. Versioned Reader/preview artifacts use `schema_version: 1`; ordinary API responses use their exact OpenAPI schema without an invented universal envelope. Public Home contains `locale`, `territory`, `hero`, `shelves` and `catalog_version`; list pages use `items`, `next_cursor` and `has_more` as declared. Only the admitted unfiltered first page is cached. Use ISO-8601 UTC times, UUID IDs, integer byte counts and durations in integer milliseconds. Do not serialize internal bucket locators or rights documents. API version `/v1` is separate from immutable `edition_revision_id`, `anchor_revision` and build ID. New fields may be added compatibly; an unsupported major schema fails closed with an update/reconnect action.

Budgets: 20 items per list page (Home shelves also obey their own bounded schema and the byte budget); 48 KiB gzip public JSON and SSR HTML separately; 64 KiB raw Reader manifest; Reader chunk at most 256 KiB raw and 64 KiB gzip; grant response at most 64 KiB raw; a grant requests at most ten units and returns only the bounded requested asset set. A manifest page has next_cursor and at most ten unit descriptors (partial-unit chunk pages allowed). A grant has at most 100 selected chunks; omitted chunk selection exceeding that count returns 422 chunk_selection_required. Split a very large unit into sequential semantic chunks at paragraph/stanza boundaries, never split a UTF-8 sequence or Bengali grapheme solely to meet a byte limit. If ten units exceed the grant budget, return a documented validation error and request fewer units; do not silently truncate. Paginate large manifests by stable cursor over unit/chunk order before exceeding the 64 KiB bound; never truncate a descriptor silently.

The private Reader manifest contains metadata and ordered `units[].chunks[]`, **no signed URL**. Each Reader chunk_id equals its asset_id (the maison_asset UUID). Each descriptor has those opaque IDs, SHA-256, uncompressed/compressed byte lengths and content_type. The parent unit carries unit_id; the private chunk contains ordered Paragraph records with anchor IDs. Offsets use Unicode code points, validated at grapheme boundaries. `content_sha256` identifies the canonical edition payload; `anchor_revision` identifies the stable semantic coordinate system. Online POST `/content/packages/grants` receives edition_revision_id, unit_ids, optional chunk_ids, device_id and purpose=online and returns `assets[]` with corresponding asset_id/chunk_id/unit_id/sha256/bytes/content_type/url/range_supported plus issued_at/expires_at. Grant URLs expire after 120 seconds, bounded by earlier rights/entitlement expiry. Prefetch at most the next authorized unit. URLs are capability data and never persisted as the offline storage key.

Hash exact canonical JSON UTF-8 bytes produced by the publisher, with NFC display text, deterministic key ordering, compact separators and no floating-point values in hashed Reader records. The Python publisher's canonicalization must be covered by fixed EN/BN fixtures; do not assume a second language's serializer produces identical bytes. Hash before transport compression; decode Content-Encoding before validating that declared hash/length. MP3/M4A hashes cover the exact original binary bytes; byte-range piece hashes cover exact offset/length slices. A root index hashes the ordered manifest records without including its own root hash; the edition hash includes only documented payload fields, not signed URLs or mutable expiry. Store the canonical bytes rather than reserializing them on each request.

TimingMap binds edition_revision_id, text_sha256 (the content root), anchor_revision, asset_id/asset_sha256, map_id, precision and measured=true. A prepared mapping artifact is independently hashed for local integrity; do not invent a second API revision field. Store monotonic integer start/end times and exact anchor IDs. A mismatched hash disables exact format switching. Missing/unmeasured mapping offers explicit unit/start selection; percentage-based estimated sync must not look verified. A correction creates a new revision and deliberate anchor migration, preserving orphaned annotation recovery. Offline switching is available only when both relevant formats and the matching map are complete and licensed locally.

The immutable build manifest maps JS/CSS/font asset paths to hashes and a `minimum_payload_schema`. The current version pointer is revalidated and never cached immutably. Keep only the current and previous shell builds while clients migrate. Do not force service-worker activation in the middle of an incompatible queue write. Reader content version and UI build version must not be conflated; a UI upgrade cannot silently rewrite a reader annotation's anchor revision.

## 5. Previews, direct audio, Stream and browser policy

Shared public delivery additionally requires explicit global public-delivery clearance for each cover and preview (including preview API bytes). A territory query is not authorization and cannot geofence an R2 public custom-domain object or a shared preview cache. A territorially restricted sample/cover uses an authorized private grant and S3 delivery, or stays unavailable until a separately qualified edge authorization design exists; no such new edge component is required in P0. Public metadata admission must omit a non-globally-cleared cover/preview URL.

A public preview is a separately generated and approved object, not the paid file with client-side clipping or blurred extra pages. The preview payload declares its exact last semantic anchor or audio duration and approved continuation boundary. The server never grants the next protected unit as part of a preview. S09/S11 display only that safe boundary plus a separately obtained real offer. A decorative peek must be independently cleared. A released Reader edition does not authorize an audio/video sample. Existing preview policy is reconciled per title; no universal “three pages/180 seconds” is presented as a live verified rule.

Online private audio uses approved progressive MP3/M4A 48/96 kbps assets. The 120-second signed GET URL supports single byte-range requests from the media element. Its signature does not authorize HEAD; use manifest metadata, or issue a separately signed HEAD capability only if explicitly needed. CORS allowing HEAD does not change that method binding. Retain one media element across mini/full players. Refresh authorization 30 seconds before a needed new request; after a legitimate expiry, obtain one replacement and retry the same semantic position. Do not loop on all 403s, change provider settings, or infer entitlement from a buffered file. A request already accepted and bytes buffered before expiry cannot be recalled. Test playback and seeking across expiry on real supported browsers before release.

Representative private audio partial response:

```http
HTTP/1.1 206 Partial Content
Content-Type: audio/mpeg
Accept-Ranges: bytes
Content-Range: bytes 1048576-2097151/5242880
Content-Length: 1048576
Cache-Control: private, no-store, max-age=0
Access-Control-Allow-Origin: https://app.example.invalid
Access-Control-Expose-Headers: ETag, Content-Length, Content-Range, Accept-Ranges
```

Configure equivalent private Cache-Control on stored objects and verify actual provider success, expiry and error responses. The API middleware cannot add headers to a direct R2 response; the direct S3 endpoint is never admitted to the app's CDN regardless of whether a provider error omits custom headers. Set exact permitted production/staging app origins, GET/HEAD methods, Range/If-Match request headers and the listed exposed headers in R2 CORS; omit credentials and use `credentials: omit` for signed-object fetches. Preflight caching (for example 600 seconds) is a CORS policy optimization, not content authorization. Reject opaque responses in the download manager. Public fingerprinted assets can use `Access-Control-Allow-Origin: *` without credentials. [R2 CORS](https://developers.cloudflare.com/r2/buckets/cors/), [HTTP range semantics](https://datatracker.ietf.org/doc/html/rfc9110#section-14).

Mark protected Stream videos requireSignedURLs. POST `/media/grants` returns the authorized 120-second playback token URL; server signing can be local, using a protected key, without an API round trip per play. Omit downloadable capability. Renew token/manifest before subsequent protected fetches and preserve the playhead; qualify long-session token renewal and captions on actual Stream player/browser combinations. Stream controls its own HLS/DASH delivery headers. Do not intercept its segments with the app service worker or claim all segment requests recheck our database. Key revocation is broad, not per-device. P0 has no offline video or video-position Trinity. [Secure Stream playback](https://developers.cloudflare.com/stream/viewing-videos/securing-your-stream/).

Use a route-specific CSP. Public cached HTML uses external fingerprinted scripts and no per-user inline executable bootstrap; safe JSON script data is serialized by Django. Start from `default-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'self'`. Permit only the configured public font/image origin, exact private R2 account endpoint, configured Stream customer domain and chosen hosted checkout domains in relevant img-src/media-src/connect-src/frame-src. Checkout routes are private and get their provider-specific policy. Use script hashes for unavoidable fixed inline code; do not put a reused personalized nonce in cached HTML or allow broad `https:`/`*` wildcards to make a player work. Allow `blob:` only if the chosen local offline player needs it. Validate all provider hostnames in staging before enforcing. Use strict-origin-when-cross-origin as the baseline, including account form HTML. Apply no-referrer only to token-bearing player/action routes after proving unsafe JSON requests carry a valid Origin and normal CSRF protection; do not break HTTPS Referer-based CSRF checks by applying no-referrer globally to account forms. Redact signed query strings and Stream tokens in logs, Sentry, support screenshots and analytics; return opaque asset IDs instead.

## 6. Explicit offline licenses and storage

HTTP cache and service-worker CacheStorage are different mechanisms. `no-store` prevents ordinary HTTP/shared caching; it does not make an intentional JavaScript CacheStorage write impossible. The generic fetch handler is network-only for private APIs/media. Only the explicit authorized download manager may save protected bytes, after `/api/v1/me/downloads` returns an offline license. Never automatically cache a private response just because it returned 200.

Download request: edition_revision_id, format reader|audio, permitted unit IDs and device_id. The returned `license_id`, device_id, valid_until, last_validated_at, revision/hash and asset descriptors are account-scoped. `valid_until = min(server_now + 24 hours, entitlement_end, rights_end, configured policy end)`; renewal is online only and rechecks current access. The maximum 24-hour policy is proposed and rights-qualified, not a DRM or immediate-revocation guarantee. Signed asset URLs are 120 seconds even when the offline license is longer. A failed/expired URL can be reissued only through the online download URL-refresh endpoint (which does not extend the license); never extend a local expiry by editing a timestamp.

Use IndexedDB `maison-v1` for licenses, package metadata, downloads, local annotation state and operation queue. Cache names: `maison-shell-{build_id}`, `maison-public-v1`, `maison-private-v1-{account_namespace}-{device_id}`. The opaque account namespace is local separation, not authentication. Save bytes using synthetic service-worker-only keys:

```
/__offline/{account_namespace}/{device_id}/{edition_revision_id}/{asset_id}/{sha256}/{piece_index}
```

The origin returns 404/no-store for these paths and the CDN bypasses them. No network fallback may turn a synthetic path into public content. Check the active local account, device, license, expiry, known revocation/rights tombstone, compatible schema and hash before serving bytes. Never expose one account's files after another account signs in.

Download sequence: estimate/reserve space → obtain license/manifest → stream into temporary namespace → verify declared lengths and hashes → atomically mark the IDB package complete → expose Offline ready. Two parallel byte requests maximum. Reader chunks and audio pieces are independently resumable; incomplete packages show paused/failed and never claim full offline readiness. An online source that changed hash must not be stitched to an old revision. Removing from device deletes only that package, not cloud progress/notes or the user's purchase.

Default user device budget is 256 MiB, configurable up to a 1 GiB app ceiling and always subject to available origin quota. Reserve 20% of the browser's estimated available headroom. `estimate()` and `persist()` are feature-detected best effort; quota is not guaranteed and the browser may evict data. Recheck availability before each piece, handle QuotaExceededError, cancel safely and offer remove/retry without deleting unsynced annotations. Display measured package bytes and approximate available space, not invented exact capacity. [Browser storage quota and eviction](https://developer.mozilla.org/en-US/docs/Web/API/Storage_API/Storage_quotas_and_eviction_criteria).

Record server time, wall-clock sample and monotonic elapsed anchor at validation. Within a running session use the monotonic clock; after restart reject suspicious backwards time or an expired/unknown deadline and require online revalidation. Browser clocks/storage/code are controlled by the device owner; this is honest-client policy, not tamperproof protection. Offline license metadata is not payment evidence. Already copied bytes can be extracted.

On local logout immediately lock that account namespace, stop playback, notify tabs, purge protected bytes, licenses and account queue, then complete/retry server logout when possible. Before an elective connected logout, allow pending personal edits to sync; do not retain another user's queue under a new account. Revoking a device invalidates its server session/licenses and denies future grants now. A reachable client purges on the next authenticated check; a disconnected device cannot receive that command and may access its existing license until expiry. A remote revoke screen states this limitation. On reconnect validate session and licenses before renewal or protected playback, and apply known rights tombstones before accepting cached metadata as current.

## 7. Offline audio Range handling

Publish SHA-256 hashes for fixed 1 MiB byte pieces and a final shorter piece, only for approved audio/offline rights. The bounded DownloadLicense references a private signed piece_manifest (URL, expiry, hash and length); fetch/verify it before going offline rather than inlining thousands of pieces in the API response. The prepared OfflinePiecePage is at most 1 MiB and 5,000 pieces, enforced on encoded bytes before Ready; split an oversized media unit before publication. Piece boundaries are storage boundaries, not random new MP3 chapter starts. Fetch source pieces with Range, verify Content-Range/length/hash, then store each as a new synthetic 200 Response. `Cache.put()` rejects a 206 Response; never put the network range response directly in CacheStorage. [Service Worker Cache.put algorithm](https://w3c.github.io/ServiceWorker/#cache-put).

The local media handler parses a single bytes range, validates it against the complete verified asset length, reads only intersecting verified pieces and streams a 206 with Content-Range, Content-Length, Accept-Ranges and MIME. A full request streams 200 without loading the entire chapter in memory. A valid suffix/open-ended range is supported; unsatisfiable ranges return 416 with `Content-Range: bytes */{length}`. Ignore a syntactically unsupported multi-range request and serve a valid full 200 stream, or use an explicitly tested client fallback; do not fabricate a multipart body. HEAD returns matching headers with no body. Recheck license before opening a local response; active playback pauses at its deadline. No new response is started after expiry. P0 qualification must prove airplane-mode relaunch, seek, suspension/resume, expiry and partial-download recovery on supported Android/iOS browsers. Unsupported clients show Stream online rather than a working-looking Download button.

## 8. Personal sync and offline learning

The bounded client queue holds only progress, annotations and saved-item mutations. Each entry has operation_id, operation type, base_version, edition/content revision and mutation payload. Queue bound: 500 operations or 2 MiB UTF-8 serialized bytes, whichever comes first. Batch POST `/api/v1/me/sync`: at most 100 operations and 256 KiB raw JSON. Coalesce only unsent progress for the same edition/format. Never discard an annotation silently; at capacity stop promising durable saves, retain the current draft where possible and offer reconnect/export. Notes are at most 8 KiB UTF-8 each. Retry safe operations with bounded exponential jitter, preserve IDs, and show Saved locally / Syncing / Synced / Conflict distinctly.

Server idempotency receipt binds operation_id to the payload digest. Duplicate same operation returns its original result; reusing an ID for a changed payload is conflict. Per-operation results allow partial batch success. A stale base_version returns conflict/current state; an auth/device failure stops the batch until reauthentication. Only accepted operations are removed. Use If-Match for normal online individual progress/annotation updates; base_version carries the equivalent precondition inside sync. Never merge progress by largest position or client time because rereading is valid. Delete tombstones prevent stale offline replay from restoring a deleted annotation.

No auth, payment, order, subscription cancellation, grant refresh, gift, device revoke, publication, quiz scoring or custom list reorder enters this queue. P0 custom Lists are fully supported online; cached list metadata is browse-only offline, with an explicit reconnect action for edits. A list contains at most 500 ordered edition IDs and uses version conflict handling. This keeps the sync protocol limited rather than inventing a second financial/catalog state machine.

Offline quiz answers are local drafts, not awarded results. On reconnection validate quiz revision, create/resume an idempotent attempt and submit to the server. Do not show authoritative correctness, completion or unlock from an offline client. If the quiz revision is no longer supported, preserve the draft and request explicit restart. P1 timed/recorded readiness and gifting have no P0 endpoint or offline queue.

## 9. Publication, withdrawal and cache invalidation

Upload immutable Reader/media/preview/cover bytes and verify hashes before opening the short publication transaction. The transaction locks the exact revision, rechecks release and rights, updates the current catalog pointer/searchable data, and inserts an outbox invalidation event. Commit the release and event together; no best-effort-only event in process memory. A failed upload/publish keeps the previous approved revision visible. No app replica relies on a long-lived in-process entitlement cache.

Record the exact emitted public URLs and dependencies: title/series/track, collection first page, home/explore first page, locale/territory variants, old/new preview and cover renditions. The canonical territory allowlist defines the finite supported storefront variants. Filter/cursor/search results are excluded from CDN admission, so publication does not have to guess an unbounded purge set. Immutable asset bytes never change in place; new revisions use new paths. Purge the mutable pointer/listing and known old public object references. Public copies already downloaded are not recallable.

Outbox fields include event_id, event_type, aggregate_id/revision, occurred_at, exact URL list or dependency reference, reason, dedupe digest, attempt count, next_attempt_at and delivered_at. The scheduler claims bounded batches with transactional skip-locked rows, releases database locks before network calls and marks results idempotently. A post-commit fast attempt reduces latency; scheduled retries provide durability if the process dies. Retry delays 30/120/600/1800/7200/21600 seconds with jitter, cap seven total attempts (initial plus six retry delays), honor vendor 429 Retry-After and alert if a critical withdrawal is pending over 60 seconds. These are operational thresholds, not a promise that a once-per-minute scheduler runs at a subminute interval. A failing critical withdrawal may be retried by the same bounded management command immediately. Batch at most 30 exact URLs per app call; obey the current plan's actual provider limits. No cache tags or prefix purge paid feature is mandatory. [Purge by exact URL](https://developers.cloudflare.com/cache/how-to/purge-cache/purge-by-single-file/).

Withdrawal order: commit DB deny/new-grant invalidation → origin mutable routes hide item or return 410/no-store → disable public preview object at origin where required → purge all recorded public URL variants → verify sample origin/CDN reads → retain staff audit outcome. Updating catalog metadata alone is insufficient. Publishing, replacement, withdrawal, rights changes, metadata, preview, cover and build releases each produce versioned events. An edition replacement never makes a previously issued private URL point to new bytes.

Expected exposure bounds are explicit: new grants denied after the authoritative commit; existing S3/Stream capabilities can work until their 120-second expiry, and in-flight/buffered bytes persist; public responses can survive their TTL or purge propagation/failure; disconnected protected copies can work until the earlier 24-hour license/rights deadline. A purge API acknowledgement is not proof of instantaneous worldwide erasure. Monitor failures and follow the takedown runbook rather than labeling a title fully recalled.

## 10. Implementation acceptance

Before production, verify two accounts/locales/territories cannot share any private response; Set-Cookie and Authorization bypass the edge; private 304/403/206 remain no-store; unknown suffix/query tricks do not gain eligibility; EN/BN URLs have distinct cached bytes. Confirm ordinary cache HIT/MISS and TTL behavior on the actual Cloudflare zone without overriding private origin headers. Verify no personalized or full paid content appears in anonymous HTML/bootstrap/search/previews.

Test publication/withdrawal across listing variants, outbox retry after process crash, 429, duplicate delivery and failed purge; verify denied grants before eventual cache cleanup. Test old revision/hash mismatch, bounded grant size, encoded chunk integrity, Bengali shaping after chunking and measured-map rejection. Exercise private Range playback through grant expiry, offline 200-piece storage/206 reconstruction, quota eviction, logout/account switch, device revoke while online/offline, clock rollback, two-tab conflicts and airplane-mode relaunch. Test sync duplicates, payload-ID mismatch, stale revisions, queue overflow and preserved annotations. Test that pending payments and offline quiz drafts never become verified success. Capture results as implementation evidence; these documents and prototypes are not that evidence.

## Draft1.1 finite expiry and upload correction

For known finite public rights, browser/edge freshness is min(configuredTTL, max(0, floor(valid_until-now))). At zero, deny/newgrantunavailable or use private,no-store; stale serving cannot cross that deadline. Unexpected revocation retains its already disclosed residual exposure. Private media is still not CDN-cached. Staff raw uploads use a separate exact-origin PUT CORS rule with required signed headers; the consumption GET/HEAD rule is not reused as an upload policy. Local development may use gated local_put/local_signed; this is not R2 transport evidence.
