# HTTPS/CDN qualification handoff

18November2026. See PENDING_VALIDATIONS.md for the single acceptance register. The Selfish Giant stays draft. Existing platform, nameservers and public DNS must remain unchanged pending separate approval.

## Prepared release

Image earnalism-maison:https-ready digest sha256:d12cf668edf3abf5c9f5175ad48ccb730f957e561b9f1e58d8d6d5399f0ee3aa passes181 Python3.13/PostgreSQL18 tests and its Node24 build/22tests. Public release da698efa96c4f0e595edfa3310fd0f522548d8d1152bd7f563e069406cce8477 contains45files/6,989,538bytes, uploaded and independently verified in the existing public bucket. Runtime STATIC_URL is the qualified public host + /static/<STATIC_RELEASE_ID>/; collectstatic/publication comes from the built image, not accumulated host bundles.

Use prepare_public_assets for local manifest generation. publish_public_assets is a network-free plan by default; --execute requires separate R2_PUBLIC_UPLOAD_KEY_ID/SECRET, the exact unchanged tree, and explicit operator budgets. No private-book, manuscript, env or map files are eligible. Public uploads are create-once and verify exact bytes/MIME/one-year immutable headers; preserve previous releases for rollout/rollback. Runtime private credentials cannot access the public bucket.

## Approved external boundary

Owner approved one separate Render Docker web service, Singapore,$7/month plus tax/usage, no workspace upgrade/higher tier. It is qualification only, not HA acceptance. Bind only reo-earnalism-maison; automatic deployment OFF; exact qualified merged-main source. Existing Google Workspace SMTP and Neon/R2 secrets belong only in that service encrypted environment, never logs or browser screenshots. Health path /api/v1/health/live; port8000; maintain direct-origin deny and staff MFA. No additional DB/Redis/disk/service. RenderFree cannot qualify currentSMTP465/587.

Owner approved pending CloudflareFreezone preparation for theearnalism.com and proposed isolated app/asset hosts. Do not change authoritative nameservers/public DNS or production routing until a complete record export, preservation diff, rollback and exact destinations are reviewed and explicitly approved. Account currently has no domain. Partial/CNAME Cloudflare setups have separate paid-plan requirements; no unapproved paid workaround.

Three scoped90day account credentials expire16February2027: private read, private upload, public deployment; all actual least-privilege checks pass. Keep public deployment key out of web runtime after deployment; backup credentials/bucket remain separate and unqualified. Zone-specific cache-purge credential will use CLOUDFLARE_CACHE_PURGE_TOKEN only after an exactzone exists/permission is approved. No DNS/admin key in runtime.

## Remaining actual acceptance

Production HTTPS canonical host/TLS/redirects/cookies/CSRF, directorigin403andlive200; static JS/MIME/fontCORS/CSP; trusted overwritten country/IP/origin headers; anonymous canonical MISS→HIT and locale/territory isolation; Cookie/Authorization/Set-Cookie/private/error bypass; exactURLpurgeAPIack plus readbackMISS/freshbody; finite-rights TTL/no stale serving. Use synthetic public brand/catalog canaries, never publish the draft to manufacture cache evidence. Immutable static asset purging on its separate host is not yet handled by the app-catalog purge adapter; do not claim withdrawal/globalrecall.

Next action: finish authorized isolated service and pending-zone preparation, then present the exact publicDNS diff for approval. Source/config checks and uploaded static bytes alone are not production CDN acceptance.
