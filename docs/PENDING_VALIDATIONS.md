# Pending validation register

Updated 18 November 2026. Integration Lane owns this single checklist for final acceptance. Keep implementation progressing in parallel; run dependent provider/device checks together once their prerequisites are ready. A source change or local test does not close a real-provider check. Only checks applicable to the enabled launch scope block that scope; optional formats and payments stay disabled until qualified.

Current constraints: The Selfish Giant stays draft; the existing platform and DNS stay unchanged. No additional paid infrastructure without owner approval. Preserve the approved HLD/LLD and 47-region publication policy.

| ID | Pending validation | Prerequisite / simplest next action | Acceptance evidence |
| --- | --- | --- | --- |
| V01 | R2 private delivery and intake | Finish the approved private-bucket upload credential and exact-origin CORS; run the bounded synthetic qualification. Delivery credential replaced with bucket-only read-only, 24-hour access. | Actual conditional upload/replay, immutable copy, SHA/byte integrity, GET/Range, unsigned/expired denial, allowed/foreign-origin CORS and cleanup; private access remains disabled publicly. Stay within 10 MB, 50 writes, 200 reads. |
| V02 | Browser-to-R2 delivery | V01; use loopback-only qualification harness and a fresh synthetic signed object. | Browser GET/Range and integrity pass; no secret/signed URL in logs or handoff; exact canary cleaned. |
| V03 | CDN HIT/MISS and cache separation | An authorized Cloudflare-managed Maison host/zone; none currently available. Prepare native rules now; do not change legacy DNS or substitute infrastructure. | Actual first MISS then HIT for eligible anonymous responses; correct browser/edge TTL; locale and trusted territory separation; Cookie/Authorization/Set-Cookie/private/error responses never shared. |
| V04 | CDN eviction and rights expiry | V03 and deployed emitted-URL capture/purge configuration. | Actual exact-URL purge followed by uncached fresh/withdrawn response; rights expiry caps freshness and grants; no stale serving after expiry. Provider acknowledgement alone is insufficient. |
| V05 | Trusted edge country and origin protection | V03; configured edge-overwritten country/origin headers. | Forged client headers/query cannot authorize; unknown country denied; direct origin protected; edge cache lookup cannot reuse another territory's response. |
| V06 | SMTP authentication and account email journey | Owner adds Workspace app password privately to EMAIL_HOST_PASSWORD. TLS/EHLO already passed. | App verification and reset messages submitted and received at approved ronik18@gmail.com; action links complete, expire/replay safely, reset revokes sessions; no credentials in evidence. SMTP acceptance and inbox receipt recorded separately. |
| V07 | Persistent Player and recovery UI | Isolated PostgreSQL18 synthetic audio fixture and current frontend build. | Real browser playback survives eligible internal navigation/history; close/account changes stop correctly; rejected queued notes can retry/edit/export/delete without duplicate effects. Synthetic audio does not certify a book audiobook. |
| V08 | Physical mobile, offline and accessibility | Stable build; actual supported Android/iOS devices and applicable offline scope. | Responsive full-cover frames, EN/BN typography, keyboard/focus/screen-reader checks; applicable download/license/expiry, offline read/play and reconnect synchronization. Unsupported formats remain disabled. |
| V09 | Integrated PostgreSQL18 and release-source checks | Finish parallel integration; review/apply new cache migration to dedicated Neon after checks. | Combined affected backend/frontend tests, build, no migration drift, pinned Python3.13 packaging and exact-head CI; pooled/direct TLS/timeouts and book draft/null live pointer preserved. Historical 37-migration evidence predates the new cache migration. |
| V10 | Production operations, load and recovery | Authorized deployment/resource configuration and any indispensable spending approval. | Health/readiness, bounded provider/database failures and retries, rate-limit headers, saturation/autoscaling behavior, observed cost limits, backup restore and rollback rehearsal on the actual deployment. Local restore is supporting evidence only. |
| V11 | Launch content and compliance | Exact-edition rights/permissions and applicable operating documents for every active region. | All 47 active regions and each offered format/action supported by retained evidence; privacy/terms/contact/retention and data-processing requirements match enabled scope. UAE/Mainland China and pending regions stay excluded. Draft acceptance does not authorize publication. |
| V12 | Payments, refunds, tax and invoices — only if enabled | Qualified merchant/test credentials, country/tax/seller facts and permitted provider operations. | Actual sandbox checkout/webhook/replay/late-capture/refund reconciliation and invoice cases; live activation requires applicable approvals. Remains disabled; do not block a launch scope that excludes payments. |
| V13 | Audio/video and learning content — only if offered | Cleared final media/editorial content; approved adapters and any spending authority. | Applicable rights, real media preparation/playback/timing, device delivery and editorial acceptance. Synthetic fixtures do not establish content or provider readiness. |

## Latest qualification results,18November2026

| Item | Current result | Evidence / remaining work |
| --- | --- | --- |
| V01 | PASS for private synthetic HTTP transport; PARTIAL for production integration | [18 HTTP checks and three successful cleanups](evidence/r2-http-qualification.json). Conditional PUT, immutable copy, SHA/bytes/type/method binding,412 replay rejection, allowed/foreign CORS, GET/Range, unsigned denial and expired grant passed. Separate exact-origin delivery/upload rules saved. Private bucket has no public development URL/custom domain. Actual retained draft assets and protected R2-backed browser/API journey now pass; see the latest milestone below. Production HTTPS origin, backup scope and durable runtime credential configuration remain pending;24-hour qualification tokens are temporary. |
| V02 | PASS for the loopback browser scope | [Browser GET/Range/SHA/private-cache result](evidence/r2-browser-qualification.json), [screenshot](evidence/r2-browser-qualification.png).64KiB synthetic object; exact canary cleaned. Production CDN is not qualified. |
| V03–V05 | BLOCKED on an authorized Cloudflare-managed host | CDN HIT/MISS, cache-key isolation, trusted edge headers, rate-limit identity and purge/expiry readback stay grouped here. Current platform/DNS unchanged. |
| V06 | PARTIAL: TLS/EHLO pass; SMTP authentication/submission/inbox pending | Superseded by the actual verification/reset receipt and action milestone below. Both requested emails were sent once and received in the approved inbox; production HTTPS links and sender DMARC policy review remain pending. |
| V07 | PARTIAL: synthetic desktop playback continuity passed | [Observed journey](evidence/player-browser-continuity.json), [screenshot](evidence/player-browser-continuity.png). Explore/EN–BN/history/Reader navigation preserved advancing playback and1.25x speed;5minute timer selection survived; close removed audio. Exact DOM identity, timer elapse, auth/account boundary and queued-note browser recovery remain pending. Fixed an actual Player grant-route404 and added a frontend/OpenAPI route audit. |
| V09 | PASS for source CI and dedicated Neon migration; production acceptance remains separate |171 backend tests,20 frontend tests, production build, seven focused configuration tests and no migration drift. New cache migration applied to existing Neon; [book readback](evidence/provider-book-draft-check.json) confirms draft/null live pointer. Pinned Python3.13 also passed171 combined tests. [Exact-source CI passed](https://github.com/ronik18/reo-earnalism-maison/actions/runs/44233552612) at `8236663`:172 backend tests,20 frontend tests and build; [record](evidence/provider-source-ci.json). |
| V08,V10–V13 | Remain pending or disabled as scoped above | No physical-device, production resilience, legal/publication, payment or real-media readiness is inferred from this milestone. |

The R2 probe exposed and fixed a real exhausted-stream socket error; another check was narrowed to the actual R2 unsigned400 `InvalidArgument` error without accepting arbitrary400 or leaked object bytes. Earlier failed runs remain private with successful cleanup. Final full probe passes. No paid infrastructure was provisioned and the real title remains draft.

## Final acceptance sequence

1. Complete source integration and V09; run V01–V02 and V06 independently when credentials are ready.
2. Once an authorized host is available, qualify V03–V05 together against the same deployment; perform V07–V08 on that build.
3. Close V10–V11 for the actual launch scope and V12–V13 only where enabled. Root reviews one release candidate, performs applicable final smoke checks and records cutover readiness.

## Closing an item

Update this table with PASS plus the dated evidence path, exact source/build, environment and enabled scope. Use PARTIAL or BLOCKED with the concrete dependency where appropriate. Keep historical evidence in its existing handoff; link it rather than duplicating checks. Never mark PASS from code presence, mocks, or a provider acknowledgement alone.

Next integration action: run grouped production edge/HTTPS, durable credential, backup and device checks when their prerequisites are available. Keep the book draft and current platform unchanged.


## Latest email and actual-book acceptance,18November2026

- **V06 PASS for configured SMTP and isolated account actions:** TLS/authentication, exactly one verification email and one reset email, actual Gmail inbox receipt, SPF/DKIM pass, received-link confirmation and410replay rejection. Reset revoked the old session/device, rejected the old password and accepted the new test password. No existing Neon or legacy account was reset. [Evidence](evidence/smtp-account-journeys.json). The test links point to loopback8012; production HTTPS links remain pending. DMARC was not reported in received authentication results; review the sender policy before production (no DNS change made).
- **V01/V02 PASS for this protected R2-backed draft scope:** the exact approved front/back JPEGs and Reader JSON total248,973bytes, uploaded to the private bucket and independently hash-verified. Browser covers load800×1200 without cuts;32paragraphs, progress, persisted gold note, EN/BN interface, completion and Saved/Finished reopening pass. Actual browser fetch of a staff-issued R2 package verifies11,940bytes, SHA256 and private/no-store. Reader SSR text itself comes from Neon; do not equate that SSR render with package transport. [Assets](evidence/r2-book-assets.json), [package browser](evidence/r2-book-package-browser.json), [journey](evidence/r2-book-journey.json).
- Existing R2 credential fields were blank when qualification resumed. With explicit owner approval, revoked the two prior tokens and created same-scope24hour private-bucket-only read and read/write replacements; restored only their four env fields while preserving SMTP/DB settings. These qualification credentials still require a durable production credential decision; no extra service or paid plan was provisioned.
- **Still pending together:** V03–V05 actual CDN HIT/MISS, trusted edge headers/cache-key isolation and purge/expiry readback; production HTTPS email links/DMARC review; physical devices/offline/accessibility; deployment load/recovery/backup; all applicable rights/operating requirements and any optional payment/media scope. The book remains draft with null live pointer; current platform/DNS unchanged.


## HTTPS/CDN preparation milestone,18November2026

- Production-image gap fixed: frontend test inputs included in Docker build; stale host bundles excluded. The exact Python3.13 image passes181 backend tests;22 frontend tests/typecheck/build pass. The initial host-native run had five subprocess-import timeouts; no check was weakened. An iCloud dataless Git exclusion file was hydrated without rewriting its contents/history. Canonical container execution passes; native recheck remains diagnostic.
- Approved public R2 static path now implemented: deterministic45-file6,989,538byte release, content-hashed namespace, separate public-only credential, conditional immutable puts and complete hash/MIME/cache-header readback. [Uploaded release](evidence/public-static-release.json). Public HTTP/CORS/CDN remain unqualified until the approved domain is active; no r2.dev/Worker substitution.
- Fonts use relative URLs; STATIC_RELEASE_ID selects the immutable CDN prefix; service-worker assets use that exact public release and credential-free CORS fetches. Offline shell is anonymous even when requested by a signed-in member; private routes are never admitted to public shell caching.
- Three owner-approved90day account credentials now expire16February2027. Actual private read/write/denied-write/cross-bucket boundaries passed; [credential evidence](evidence/durable-credential-qualification.json). Existing24hour tokens are unchanged; no backup permissions were granted.
- Production-mode check passes without errors and retains two explicit Django warnings: HSTS subdomain inclusion and preload remain disabled until the complete domain scope is reviewed. This check used reserved example hosts with networking disabled; it is not production HTTPS evidence.
- Owner approved one isolated Singapore Render service at$7/month plus applicable tax/usage, no workspace upgrade; this qualifies the HTTPS stage only, not the approved2–6replica HA/autoscaling target. Deployment connection/secrets and pending Free Cloudflare zone preparation are authorized; public DNS/nameservers require a separate exact-diff approval. The book remains draft/current platform unchanged.


## Deployment handoff status,18November2026

- Exact-head CI passed for `3fdd7426c02eb6c8b540cbc53e23120b45d7d404`: [run44251719606](https://github.com/ronik18/reo-earnalism-maison/actions/runs/44251719606).
- Render form prepared for `reo-earnalism-maison-qa`, Docker/main, Singapore, $7/month, health `/api/v1/health/live`, auto-deploy Off. Private provider variables imported; public deployment credential excluded. Final creation requires the owner's Add Card step ($1 temporary verification authorization). No web service has been created; HTTPS qualification remains pending.
- Cloudflare Free-zone preparation reached domain onboarding only. The default Bot Preference Sync would prepend robots.txt rules; disabling it was rejected by automatic approval review as outside zone-only approval. Requested explicit setting approval; zone creation and DNS record review remain pending. No public nameserver/DNS/traffic changes.
- Independent frontend chat found incomplete P0 screen/state coverage. Owner authorized that chat to complete missing screens in an isolated checkout based on3fdd742; root retains final integration. Backend/provider-dependent controls remain truthfully gated. Physical Android/iOS acceptance remains pending.

Next integration action: complete approved provider prerequisites, verify actual deployed HTTPS, prepare the exact DNS diff for separate approval, then run V03–V05 together.


## Cloudflare pending-zone preparation,18November2026

Owner explicitly approved disabling Bot Preference Sync; the onboarding switch was verified Off before proceeding. The $0 Free zone for theearnalism.com is now prepared and awaiting nameserver activation. Assigned nameservers: cesar.ns.cloudflare.com and ligia.ns.cloudflare.com. Existing authoritative ns1.dns-parking.com/ns2.dns-parking.com remain unchanged; no registrar, public DNS or traffic changes were made.

Automatic scan found13records:2A,7CNAME,2MX,2TXT. The scan is not a complete Hostinger zone export. All9 scanned A/CNAME records default to Proxied, including FTP, mail discovery and DKIM aliases; these pending defaults require review/correction before any activation. Current apex/Vercel and api/Railway targets must be preserved. Obtain full existing-zone parity (including uncommon records, mail, verification, CAA and DNSSEC/DS status), prepare the exact diff and seek separate DNS approval. Do not activate from the scan alone.

V03–V05 remain pending: no active Maison app/assets host, real CDN HIT/MISS, cache isolation or purge readback. Render Add Card is still pending; no qualification web service has been created.


## P0 frontend integration,18November2026

The owner-authorized frontend lane supplied a43-file patch based on3fdd742 plus availability follow-up. Root integrated it with actual403/404/500 handlers. Public gold artwork, onboarding, personal Home, collection/Series destinations, gated Video, owned Checkout, Reader preview/format dialogs, Settings, Vault and download recovery now have source implementation. [Browser evidence](evidence/frontend-browser-validation.json) covers Chromium desktop1440/mobile390 and Bengali360 widths; original synthetic fixture flows only. Physical Android/iOS, Safari/WebKit and assistive-technology/offline-device acceptance remain V08. Do not claim26fully accepted native screens.

Retained backend dependencies: bounded audio preview object, qualified Stream, real Series/episode data, pagination beyond Saved/Lists100 and Continue/Finished20, existing subscription cancellation/mandate/invoice delivery APIs. Payments/media remain disabled until applicable qualification. Vault territory projection must be reviewed before international acceptance. These are consolidated dependencies, not evidence of production readiness.

New frontend bundles/art require a new immutable static release; the earlier45-file uploaded release does not contain this patch. No additional upload is implied by source integration. Root will prepare the new manifest and reconcile any upload budget before provider writes. The Selfish Giant remains draft/current platform unchanged.

Final support follow-up adds an online-only contact form in Settings and system errors, using the existing/contact API and accepted-for-processing wording. Root fixed its missing Settings mount. Final local static summary:54files,7,258,380bytes, release088fe0650e532f527289e68c2ac8c8ac9fcdf32a37f6274f01312b837298ad56. No support messages or additional provider uploads were sent.

Integration continuity: iCloud hydration blocked the original checkout's Git ignore/index operations. Root preserved all57scoped files in two durable SHA256-verified exports (archive ba0bd42433f680032be95c90ad0f5cbcdf88ee57e93e56d9c115b389ac3c1211), then continued in /tmp/maison-frontend-integration-20261118 from3fdd742. Every copied file was hash-verified. Original checkout and unrelated contracts.test.mjs formatting are preserved; no lock deletion/reset/stash. Root is the sole writer. Canonical Docker checks passed; exact-head CI remains authoritative for the final committed test set.
