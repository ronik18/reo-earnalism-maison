# Maison HTTPS and CDN qualification handoff

Updated 18 November 2026. Integration Lane owns provider changes and source promotion. **The final public URL remains https://theearnalism.com.** Maison currently uses isolated validation hostnames; legacy application/backends and apex/www/API destinations are preserved. The Selfish Giant remains draft with a null live pointer and unchanged content hash.

## Current source and service

- Private repository: https://github.com/ronik18/reo-earnalism-maison.
- Render qualification service `srv-dbunbd8jo6nc73akbng0`, Singapore, approved $7/month plus applicable tax/usage, 0.5 CPU/512 MB. Auto-deploy Off. No workspace upgrade, new database, Redis, disk or additional service.
- Deployed backend source: `b588d4c6176acd9e74477cae9ed2ba5928060e12`. [Branch CI](https://github.com/ronik18/reo-earnalism-maison/actions/runs/44298969664), [main CI](https://github.com/ronik18/reo-earnalism-maison/actions/runs/44306964748): 227 backend tests, 26 frontend tests, strict TypeScript, build and migration checks pass. Docker build passes. No new database migration.
- Later source-only browser CSS correction: `36b771ddede39bb20f68412141cc98e6d81c91e1`, [exact-head CI](https://github.com/ronik18/reo-earnalism-maison/actions/runs/44320040439). Four CSS lines fix native select sizing and card text wrapping. 138 accepted Safari/Firefox/WebKit browser/viewport records, 23 P0 families, zero recorded errors. Physical Android/iOS are not certified by browser viewport tests. This source promotion does not deploy its new static release.
- Qualified existing public static release: `19e40009002433e09db905c865b34d85da4c8d457b5630431e135dfc71b40142`, 54 files, 7,266,812 bytes. New CSS release `27498b626af4978ef89a304da7856cfd8493f0dc006e815c3e1b787b18f9b694` is prepared offline, 54 files/7,267,320 bytes; only CSS changes by508 bytes. It is not uploaded or selected in Render. Do not mix source/static IDs during its later rollout.

## Approved provider state

Cloudflare Free zone `303b0b17a353a6fb65dfcadad5932214` uses `cesar.ns.cloudflare.com` and `ligia.ns.cloudflare.com`. All16 legacy records and MX priorities were preserved DNS-only. Four approved former14,400-second TTLs use Auto: API CNAME, both MX and Railway verification TXT. All other TTLs match. [Legacy readback](evidence/cloudflare-activation-legacy-readback.json) records website/API health200. Hostinger configuration is retained for rollback; nameserver rollback is not instantaneous.

`maison.theearnalism.com` is proxied to the actual Render hostname `reo-earnalism-maison-qa.onrender.com`, whose custom-domain certificate is issued. `assets-maison.theearnalism.com` is attached by the official workflow to the existing public R2 bucket. It contains public UI assets, not books/manuscripts/secrets. TLS minimum1.2 on this attachment; Cloudflare origin mode Full (strict). No r2.dev exposure. Bot Preference Sync remains disabled as approved.

The private R2 bucket has no custom domain or public development URL. Its prior local-origin policies remain, with an additive GET/HEAD/Range policy for exact https://maison.theearnalism.com. HTTPS preflight204 and foreign-origin403 pass; unsigned nonexistent-key request is denied400. This is transport-boundary evidence, not the authenticated package journey.

## Effective cache and origin rules

1. Exact app host request transform SET-overwrites `x-maison-origin` with the existing secret and `x-maison-country` with `ip.src.country`. No secret is sent to asset/legacy hosts. Origin remains protected; liveness alone is public and readiness also needs the health-probe secret.
2. Default app cache bypass.
3. Separate EN and BN eligible rules for exact `/api/v1/home`. Normal GET/HEAD requires no Cookie or Authorization header (`has_key` handles case/empty values), the active territory whitelist and exact locale/territory query matching actual edge country before lookup. Full URL key retained; origin TTL/no-store/private/error behavior respected, no forced TTL.
4. Internal PURGE is included in each exact-host/path rule so the existing exact-URL API purge can match without absent visitor geolocation. External PURGE returns400/private-no-store and cannot retrieve catalog data. Other app routes remain uncached during this bounded qualification.

The provider allows one concat per expression, hence two locale rules. Initial header-name case assumptions and missing internal PURGE matching were caught and corrected by actual probes. Their failures remain retained as resolved evidence history, not current PASS inputs. [Current expressions/protocol](CDN_ACTIVATION_VERIFICATION.md).

## Actual acceptance

- Certificate-valid HTTPS, redirect, HSTS, liveness200 and protected database/schema readiness200. Direct origin and missing probe denied403.
- Public CSS/JS/art MISS→HIT; Bengali font HIT. All sampled bytes/hashes/MIME match the54-file manifest and exact Maison CORS.
- Actual IN/MRS public-home EN/BN MISS or revalidation→HIT. Mixed-case and empty Cookie/Authorization, private endpoints, malformed queries and wrong-country variants are never shared HITs. Draft is denied404.
- Asset dashboard URL-only purge did not evict its Origin variant. Approved API purge with that exact Origin does: HIT→MISS→HIT and unchanged expected hash.
- Existing application `purge_catalog_cache` adapter is configured and acknowledged successfully inside the actual Render runtime. Independent exact-URL readback verifies HIT→MISS→HIT. The adapter's own result correctly remains acknowledgement-only (`readback_verified:false`); it does not fabricate eviction evidence.
- Browser HTTPS English/Bengali navigation, existing isolated member sign-in/settings/logout and signed-in draft denial passed. Staff login/MFA boundary is present; authenticated staff Reader/package journey remains awaiting owner authenticator enrollment.

Evidence: [HTTP matrix](evidence/cdn-activation-http.json), [assets](evidence/cdn-public-assets-http.json), [app purge](evidence/cdn-app-exact-purge.json), [actual adapter](evidence/cdn-app-provider-adapter.json), [asset Origin purge](evidence/cdn-asset-origin-purge.json), [source/runtime](evidence/render-cdn-final-source.json), [draft state](evidence/post-cdn-book-draft-state.json).

## Credentials and outstanding work

The owner-approved non-expiring token grants only Cache Purge on this exact zone. It is stored in ignored mode0600 local provider/Render profiles and encrypted Render environment, never Git or evidence. Existing private-read/private-write/public-deployment R2 tokens still expire16February2027; their renewal remains tracked separately. The public deployment key remains excluded from web runtime. No DNS/admin token was added.

Public HTTPS DNS-over-HTTPS answers confirm the Cloudflare delegation and Maison A records. A later local network lookup still returned the old Hostinger zone/NXDOMAIN, blocking a fresh Chrome open. This is recorded separately; no local browser/OS/router DNS setting was changed. [Propagation recheck](evidence/dns-propagation-recheck.json). Owner can retry on another network or manually choose temporary Secure DNS and restore it afterward. Browser tool policy blocks internal Chrome settings pages; it was not bypassed.

Remaining validations stay in [the single checklist](PENDING_VALIDATIONS.md): owner MFA/live staff Reader, production HTTPS verification/reset links and DMARC review, matching new CSS asset rollout, physical devices/offline/accessibility, actual load/HA/autoscaling/restore/failure recovery, and applicable launch rights/operating requirements. One$7instance is not HA acceptance. Book publication and apex cutover have not occurred; additional paid infrastructure needs approval.

Historical pre-activation handoff is retained at [the prior snapshot](evidence/https-cdn-handoff-before-activation.md).
