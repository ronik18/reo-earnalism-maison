# Maison DNS change proposal

Prepared 18 November 2026. **Proposal only: no public DNS, nameserver or traffic change is authorized by this document.** The Selfish Giant remains draft; existing Vercel/Railway destinations remain unchanged.

## Evidence and scope

Source: [authenticated Hostinger inventory](evidence/hostinger-authoritative-dns-inventory.json), all 16 displayed DNS rows. This authenticated inventory supersedes the incomplete 13-record Cloudflare scan. The export button was clicked but the downloaded zone file was not located; do not describe this as a parsed full zone export. Verify the pending zone against all rows below before requesting activation. The inventory's Render status is historical; the subsequently created qualification service is `srv-dbunbd8jo6nc73akbng0`, live on source `5ecc5ca`; certificate-valid HTTPS, liveness and protected database/schema readiness passed.

## Preserve these existing records

All A/CNAME records below must be **DNS-only**, including apex, www, api, FTP and mail discovery/DKIM. MX/TXT are inherently unproxied. Preserve TTL seconds and MX priority. Hostinger displays priority 0 for non-MX records; that is not a Cloudflare priority field. TXT quoting in this table reproduces the inventory presentation; enter the TXT value once without introducing additional literal quote characters.

| Type | Name | Exact content | TTL seconds | MX priority | Cloudflare state |
|---|---|---|---:|---:|---|
| CNAME | `hostingermail-c._domainkey` | `hostingermail-c.dkim.mail.hostinger.com` | 300 | — | DNS-only |
| CNAME | `hostingermail-b._domainkey` | `hostingermail-b.dkim.mail.hostinger.com` | 300 | — | DNS-only |
| CNAME | `reach-b._domainkey` | `reach-b.dkim.reach.hostinger.com` | 300 | — | DNS-only |
| CNAME | `hostingermail-a._domainkey` | `hostingermail-a.dkim.mail.hostinger.com` | 300 | — | DNS-only |
| CNAME | `reach-a._domainkey` | `reach-a.dkim.reach.hostinger.com` | 300 | — | DNS-only |
| CNAME | `www` | `cname.vercel-dns.com` | 3600 | — | DNS-only |
| CNAME | `autodiscover` | `autodiscover.mail.hostinger.com` | 300 | — | DNS-only |
| A | `ftp` | `145.79.210.127` | 1800 | — | DNS-only |
| TXT | `_railway-verify.api` | `"railway-verify=728bb5d747a223a5f324dcb0d23971004844e329f892205092f50ddf01240893"` | 14400 | — | DNS-only |
| CNAME | `api` | `zg6cgit5.up.railway.app` | 14400 | — | DNS-only |
| CNAME | `autoconfig` | `autoconfig.mail.hostinger.com` | 300 | — | DNS-only |
| TXT | `_dmarc` | `"v=DMARC1; p=none"` | 3600 | — | DNS-only |
| TXT | `@` | `"v=spf1 include:_spf.mail.hostinger.com include:_spf.reach.hostinger.com ~all"` | 3600 | — | DNS-only |
| MX | `@` | `mx1.hostinger.com` | 14400 | 5 | DNS-only |
| MX | `@` | `mx2.hostinger.com` | 14400 | 10 | DNS-only |
| A | `@` | `76.76.21.21` | 3600 | — | DNS-only |

## Pending-zone reconciliation: no public activation

The prior scan contains 13 rows. Add these three missing rows to the pending zone, preserving the table values above:

- CNAME `reach-a._domainkey` → `reach-a.dkim.reach.hostinger.com`, TTL300, DNS-only.
- CNAME `reach-b._domainkey` → `reach-b.dkim.reach.hostinger.com`, TTL300, DNS-only.
- TXT `_railway-verify.api` → the exact verification value in the preservation table, TTL14400.

Review all imported A/CNAME proxy flags: the scan defaulted them to Proxied. Set the preserved legacy records DNS-only in the pending zone. Reconcile every TTL against the authenticated inventory rather than scan defaults. No legacy record is deleted or retargeted. This document does not execute these preparations.

## Isolated Maison additions requiring explicit public-DNS approval

| Item | Proposed destination/configuration | Status |
|---|---|---|
| CNAME `maison.theearnalism.com` | `reo-earnalism-maison-qa.onrender.com` (verified service Settings; Singapore, 0.5CPU/512MB; health path `/api/v1/health/live`). Proxied for reviewed Maison edge rules; TTL Auto for proxy. | Exact target verified; public DNS approval still required |
| `assets-maison.theearnalism.com` | Official Cloudflare R2 custom-domain attachment to the existing Maison **public** asset bucket. Let the R2 attachment create/manage its documented DNS target; do not CNAME to an S3 API endpoint or private bucket. | Requires public-DNS approval before attachment |

No private bucket custom domain or public development URL. No apex/www/api cutover, new paid service, or additional domain is included. Read back any provider-supplied validation records before adding them; they are not pre-authorized by a placeholder.

## Nameserver proposal: separate approval boundary

- Current authoritative nameservers: `ns1.dns-parking.com`, `ns2.dns-parking.com`.
- Proposed Cloudflare nameservers: `cesar.ns.cloudflare.com`, `ligia.ns.cloudflare.com`.
- Preserve all 16 existing record destinations/TTLs/priorities before switching.
- Registrar panel showed empty DS-add fields and public DS lookup returned no answer. Recheck DNSSEC/DS before the switch; do not invent or change DS records as part of this proposal.
- Request explicit approval for the exact completed record diff and nameserver switch. Pending-zone preparation approval is not public-DNS approval.

## Qualification and rollback

Before approval: capture the complete pending-zone readback, confirm all 16 preservation rows plus the two isolated Maison additions and any separately reviewed provider validation records, verify the actual Render hostname and origin health, and prepare edge rules without exposing the private bucket. Keep Bot Preference Sync disabled as previously approved.

After approval: verify authoritative NS convergence; compare all preserved records and mail/DKIM/SPF/DMARC/verification values; confirm existing apex/www/API behavior; then qualify Maison HTTPS, origin protection, static CORS/MIME, canonical anonymous MISS→HIT, private/country/query bypass, and exact-URL purge acknowledgement plus MISS/fresh-body readback. Use synthetic public canaries, never publish the draft book for evidence. See [the consolidated checklist](PENDING_VALIDATIONS.md).

Rollback if preservation or existing-platform checks fail: restore the recorded Hostinger nameservers, which must remain configured and intact, and verify authority/legacy endpoints again. Nameserver propagation is asynchronous; this is not an instantaneous rollback guarantee. Do not delete existing Vercel, Railway or Hostinger configuration during qualification.


## Saved pending-zone readback

All16existing records are now present, DNS-only, with exact values/names/types/MX priorities verified.12TTLs matchsource; apiCNAME, bothMX and RailwayverificationTXT retainAuto instead ofsource14400seconds because the dashboard lacks4hourTTL. Treatthese as explicitTTLexceptions in anyactivationapproval; notexactTTLparity. NoauthoritativeDNSornameserverchangesmade. See evidence/cloudflare-pending-zone-readback.json.
