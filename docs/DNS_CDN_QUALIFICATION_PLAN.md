# Isolated Maison HTTPS and CDN qualification

Status: 18 November 2026. No public DNS, nameserver or legacy deployment changes made.

## Parallel lanes

1. Render: prepared Docker/main service `reo-earnalism-maison-qa`, Singapore, approved $7/month qualification tier, auto-deploy Off. Creation is waiting for the owner to complete Add Card. Verify the assigned hostname, exact deployed source and uploaded static release, HTTPS, anonymous liveness, protected database/schema readiness and direct-origin rejection. One instance is not HA/autoscaling acceptance.
2. DNS/CDN: pending Cloudflare Free zone prepared. Hostinger is signed out; authenticated complete zone export is pending. Public DNS snapshot is bounded evidence, not a complete export. Prepare a reviewed record diff only after export and actual Render hostname are available. Request approval before any public DNS or nameserver change.

## Preserve existing services

| Existing record | Observed destination | Treatment |
| --- | --- | --- |
| Apex | 76.76.21.21 | Preserve existing Vercel destination |
| www | cname.vercel-dns.com | Preserve existing Vercel destination |
| api | zg6cgit5.up.railway.app | Preserve existing Railway destination |
| MX | mx1.hostinger.com / mx2.hostinger.com, priorities 5/10 | Preserve mail delivery |
| SPF, DMARC, DKIM, autoconfig, autodiscover | Existing Hostinger records | Preserve values and mail DNS-only behavior |

Before activation compare all exported names, record types, values, TTLs and priorities, including AAAA, SRV, wildcard, verification and delegations; verify registrar DS/DNSSEC status. The pending quick scan has default proxy settings that must not be activated unchanged: FTP and mail-related names require DNS-only treatment. Public lookup alone cannot prove completeness or DNSSEC status.

## Proposed isolated additions, not authorized DNS mutations

- `maison.theearnalism.com`: actual assigned Render hostname, to be read back after service creation.
- `assets-maison.theearnalism.com`: official custom-domain attachment to the existing Maison public R2 bucket. Never expose the private bucket or substitute its S3 endpoint.
- Preserve apex/www/api and all mail records. No Worker or paid upgrade is proposed.

## Consolidated acceptance sequence

1. Qualify Render HTTPS and exact source/static release; check production email links and authenticated account journeys.
2. Prepare full DNS diff and obtain separate approval before changing public DNS/nameservers.
3. Validate Free-plan rule syntax before applying it. Overwrite trusted origin/country headers at the edge; direct protected-origin requests must fail. Readiness requires both origin and health-probe credentials.
4. Admit only anonymous public allowlisted responses to shared cache. Validate territory against actual edge country before cache lookup. Cookie/Authorization/private/no-store/Set-Cookie/error responses must not become shared cache entries.
5. Verify actual MISS then HIT with synthetic public content, locale/territory isolation, font CORS/MIME/CSP, exact single-file purge acknowledgement followed by fresh MISS/body, and expiry. Include GET and HEAD in cache-rule review.
6. Confirm asset-host purge scope separately: current application purge adapter accepts the app host only. Do not claim asset eviction or global recall without proof.
7. Keep load/HA/autoscale, recovery/restore, physical-device and accessibility checks in `PENDING_VALIDATIONS.md`. Additional paid infrastructure still needs approval.

The Selfish Giant remains draft with a null live pointer. Never publish it to manufacture CDN evidence. Existing Vercel/Railway remain active until a separately authorized, validated cutover.

## Hosting decision

Maison does not require Vercel in the approved architecture: one Django Docker application serves the UI and same-origin APIs on Render, Neon stores relational data, and R2/Cloudflare deliver assets. This reduces deployment and cross-origin integration overhead for this application. Vercel can also host Django; this is an architectural simplification, not a claim that Render is universally better or cheaper. Render autoscaling requires a Pro workspace or higher; the approved single $7 qualification service does not satisfy HA/autoscaling requirements.

References: https://render.com/docs/deploy-django ; https://render.com/docs/scaling ; https://vercel.com/docs/functions/runtimes/python
