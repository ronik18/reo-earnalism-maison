# Apex cutover runbook: theearnalism.com → Maison

Approved by the owner on 22 November 2026. **Hold:** the owner requires Maison to be fully ready before the visitor-facing steps (3–6) run. The approved design keeps https://theearnalism.com as the final public URL ([handoff](HTTPS_CDN_DEPLOYMENT_HANDOFF.md)). The stack stays Render + Neon + Cloudflare (CDN, R2, Stream); Railway and Redis are not added. The legacy Vercel and Railway projects, `api.theearnalism.com` and all mail, DKIM, SPF and DMARC records stay untouched for the rollback window.

## Staged on 22 November 2026 (no visitor impact)

| Step | Change | Readback |
|---|---|---|
| 1 | Render service `srv-dbunbd8jo6nc73akbng0`: custom domain `theearnalism.com` added (Render also added `www.theearnalism.com`). | Both `unverified` until DNS points at Render; `maison.theearnalism.com` stays `verified`. |
| 2 | Cloudflare zone `theearnalism.com`: the origin/country request transform and the three Maison cache rules now match `http.host in {"theearnalism.com" "maison.theearnalism.com"}`. | Rules read back enabled; apex is DNS-only so they do not apply yet. Maison liveness 200; legacy apex 200. |

## Remaining steps, in order

Prerequisite: add `https://theearnalism.com/api/v1/auth/google/callback` to the Google OAuth client's authorized redirect URIs in Google Cloud Console. The web-client redirect list has no public API, so a person with console access does this.

3. DNS: change apex `A 76.76.21.21` (DNS-only) to `CNAME theearnalism.com → reo-earnalism-maison-qa.onrender.com`, proxied. Set `www` proxied. Wait for Render to mark both custom domains verified.
4. Render environment: `PUBLIC_BASE_URL=https://theearnalism.com`; add `theearnalism.com` to `ALLOWED_HOSTS`; add `https://theearnalism.com` to `CSRF_TRUSTED_ORIGINS`. Keep the `maison.` values during the transition. Saving redeploys; confirm the deploy is `live`.
5. Enable the existing disabled Cloudflare redirect rule "Maison and www canonical alias - GET HEAD" (302 to the apex, query preserved). Change to 301 only after a stable period.
6. Verify: apex liveness, `maison.`/`www.` → apex redirect, origin secret accepted on the apex, then run `npm run e2e:production` from India with `MAISON_E2E_BASE_URL=https://theearnalism.com`. Existing `maison.` sessions end because session cookies are host-only.

## Rollback

Restore the apex record to `A 76.76.21.21` DNS-only and `www` to DNS-only `CNAME cname.vercel-dns.com`; disable the redirect rule; revert the three Render variables and redeploy. DNS propagation is asynchronous.
