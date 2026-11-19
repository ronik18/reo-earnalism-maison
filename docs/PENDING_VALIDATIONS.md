# Maison current acceptance checklist

One current register. Integration Lane alone owns integration, provider changes and release decisions. Earlier snapshots are [preserved as history](evidence/validation-history-before-scheduled-activation.md).

**Preserved:** The Selfish Giant remains draft, null live pointer,32paragraphs and original manuscript SHA. Legacy apex/www/API and DNS are unchanged. No additional spending or DNS changes without approval. Full approved P0/HLD/LLD remains binding.

**Geographic meaning:** “Global compliance” means every active jurisdiction in [the authoritative policy](../contracts/publication-policy.json), currently47; not every country or whole continents. AE/Mainland CN and pending entries are excluded; HK/MO/TW remain separate. Platform/account qualification and exact-edition publication clearance use this same geographic scope, with separate substantive evidence.

## Completed — reuse unchanged evidence

| Lane / ID | Verified acceptance | Evidence |
| --- | --- | --- |
| Draft book / V01,V09 | Staff MFA,32-paragraph Reader,complete covers,notes/preferences/progress/Saved/Finished; PG18/43migrations. Book remains draft. | [Live book](evidence/live-draft-book-final.json), [current invariants](evidence/activation-invariants.json) |
| HTTPS/CDN / V03–V05 | Isolated HTTPS,public asset and canonical EN/BN Home HIT/MISS/exact purge,origin/country/private/draft boundaries. | [CDN handoff](HTTPS_CDN_DEPLOYMENT_HANDOFF.md) |
| Account email / V06 | Actual verification/reset HTTPS and inbox receipts; replay/session/password checks; SPF/DKIM pass. No repeat sends needed. | [36checks](evidence/https-email-qualification.json) |
| Frontend/mobile / V08 | Desktop/member flows,32virtual mobile groups,4cold-offline contexts,6geometry checks; physical UAT owner-deferred/non-blocking. | [Virtual](evidence/mobile-virtual-current.json), [independent rollout](evidence/isolated-rollout-independent.json) |
| Source integration | Reviewed backup-reference/restore code on main171c794; exact-head CI44456409856 passed304backend tests,frontend check/build,migrations/no drift;29focused backup tests passed. UI/static release unchanged. | [CI](https://github.com/ronik18/reo-earnalism-maison/actions/runs/44456409856) |
| Maintenance / V11 technical | Bounded cleanup plus actual provider Scheduled runs,distinct successful DB receipts,cleared leases; empty repeat. Narrow audit/support cleanup and hold/lease safeguards tested. | [Activation](evidence/isolated-provider-activation.json), [first](evidence/maintenance-automatic-first.json), [second](evidence/maintenance-automatic-second.json) |
| Database/archive / V10 isolated | Approved Launch0.25–2CU/7day history active. SELECT-only backup role; private bucket-only token tested. Actual automatic daily/monthly encrypted archive/readback; same archive restored locally,all60table counts/content/column hashes match. Normal export03UTC restored. | [Activation](evidence/isolated-provider-activation.json), [restore](evidence/scheduled-archive-restore-result.json), [scope](evidence/archive-scope-qualification.json) |
| HTTPS after activation | Liveness200,protected DB/schema readiness200,draft catalog404,legacy apex200; verified TLS. | [Protected actual checks](evidence/activation-https-result.json), [independent7/7](evidence/activation-independent-final.json) |

## Remaining — one next action each

| Item | Scope and next action |
| --- | --- |
| V10 production operations | Current$7single web instance and approved Launch/native7-day-log exceptions qualify isolated operation,not productionHA/autoscaling. Qualify approved2–6replicas/Scale baseline,actual recovery/load/monitoring and nativePITR separately; ask before extra spending. A successful logical archive restore does not provePITR/HA. |
| V11 operating/legal | Notices and agreed retention behavior are implemented/tested. Complete supported platform/account qualification across the same47jurisdictions,including actual processor/transfer terms and applicable all-ages obligations. No new child-account flow authorized; declining a feature does not waive applicable obligations. [Account report](ACCOUNT_COMPLIANCE_QUALIFICATION_CURRENT.md). |
| V11 support/logs | Business mailbox remains operator-managed. SUPPORT_EMAIL form destination remains unset; public mailto works. Qualify actual support delivery/resolution/holds when enabled. Native7dayRender logs are an isolated exception;30day production log baseline is unchanged. Do not claim aged deletion from a newly created archive or support case. |
| V11 publication | Reconcile exact edition/assets/offered formats/actions rights and applicable publication evidence across all47active regions. Keep The Selfish Giant draft throughout this task. |
| V02,V07,V12–V13/fullP0 | Frozen frontend receipts cover22 local Reader/audio/offline/quiz checks; separate measured sample and controlled video-renewal/Google UI pass in Chromium,WebKit and Firefox. Actual private R2 CORS/full/Range browser checks passed. [Scoped receipts](evidence/p0-frontend-20261119/frontend-validation.json). Combined candidate tests/CI, matching migration/deployment and actual Google/Stream/merchant acceptance remain distinct. Controlled video is not provider qualification; no live financial mutation was performed. Disabled P0 features are not silently waived. |
| Google OAuth qualification | Approved existing client fields saved only in private configuration; isolated callback saved and read back, existing URLs preserved. Client remains **Testing**, so only registered test users can sign in. Deploy matching tested source/profile, then validate sign-in/link/reauthentication; audience publication is separate from the approved callback change. [Configuration receipt](evidence/google-oauth-configuration-20261119.json). |
| Credential renewal | Private/public/archive R2 credentials expire16February2027; renew with overlap before expiry. Purge-only credential is durable. Production age identity remains owner-held,local,ignored600; only public recipient is on Render. |
| Final release | No apex cutover/public book launch authorized by this qualification. Preserve one qualified candidate and prepare exact cutover/rollback diff for the applicable approved release action. |

## Working rules

Reuse valid evidence; one scoped check per changed behavior and exact-headCI at integration. Preserve historical work and receipts. No force push,legacy mutation,book publication,additional spending or DNS change is implied. Conditional later features remain disabled until their own evidence exists; optional studies are not new blockers.
