# Earnalism supported content release workflow

Owner direction, 26 October 2026: remove unnecessary repeated approvals and bottlenecks across covers, Reader editions and audiobooks. This is standing process authorization, not evidence that every title, right, voice or paid budget is approved.

## Authority carried forward

A request to generate or publish a named title authorizes routine work within that title's recorded scope: preparation, validation, narrow fixes, draft intake, exact-head gated merge/manual deployment and publication when the owner's release scope and objective gates permit it. Do not ask to approve each implementation step, pin update, test, read-only inspection or supported fallback. Reuse existing title/rights/voice/budget approval; do not ask again merely because CI, code revision or adapter changed without materially changing the approved outcome.

If a genuinely new paid budget, rights declaration, voice/model license, consequential wallet debit, destructive operation or external credential entry is indispensable and outside existing scope, collect the missing items in one concrete request. A known defect is an engineering task, not a reason to ask permission to fix it. Unknown write outcome requires read-only reconciliation before any further write. Do not retry failed provider generation/settings/text-hash combinations blindly.

Owner-private sign-in only when authentication expired/revoked and authorized customer acceptance can proceed. Existing Earnalism authentication also authenticates listening; no separate audiobook login. Do not ask for sign-in while waiting for CI.

## Whitelisted-region publication policy

Owner instruction,17November2026: publish a book only when its exact edition and every offered format/action are legally compliant in **all active whitelisted regions**. Use the active project's authoritative region list; Maison uses `contracts/publication-policy.json` in the dedicated `reo-earnalism-maison` repository. UAE (AE) and Mainland China (CN) are out of scope. Pending, unknown and other excluded jurisdictions are not whitelisted and must not receive delivery. HK, MO and TW retain their separately assessed entries; do not silently merge their regimes with CN.

Keep country/source/permission evidence private and bind clearance to the exact text and assets. Original-text term expiry, draft review, generated artwork or CI success alone is not full publication clearance. Resolve any applicable distribution/public-domain permission and format/download licence in every whitelisted region before publishing; otherwise keep the book draft/held. Do not silently narrow the whitelist for a difficult title, expand it from research alone, or add a worldwide wildcard. Change the approved whitelist only with supported evidence and explicit owner approval. Excluded jurisdictions do not block work for the approved scope. This policy does not itself publish a title, authorize paid infrastructure or replace the approved HLD/LLD and existing release checks.

## One release record, one release lane

Reuse the repository's supported workflow and current title checkpoint. Track exact title/edition, rights/use/territory, approved covers/voice, immutable asset hashes, measured alignment, primary/DR identities and receipts, applicable checks, deployed revision, actual acceptance and one next action. Avoid parallel wrappers, successive approval packages and new supervisors/caps/outages. Keep one focused PR and canonical Integration Lane. Follow current AGENTS.md and owner authority. Being behind origin/main is a reconciliation task, never a blanket implementation stop. Preserve parked commits, dirty files and remote history; fast-forward a clean owned checkout when possible, continue disjoint work and reconcile overlaps by intent. Use a named isolated preparation checkout when canonical is occupied or unavailable. One Integration Lane writer checks the combined diff against fresh main and runs affected checks before a normal commit/push. No force push, reset, stash, deletion, unrelated merge or added release/spending authority is implied. Keep source/evidence durably outside temporary compute.

## Work only on missing evidence

Reuse unchanged valid assets and checks by their hashes and relevant inputs. Do not repeat generation, uploads, full listening or deployment because an unrelated artifact changed. Requalify only dependencies affected by a change, plus required release checks. A frontend-only fix does not justify a backend deployment; canonical backend cover data does. Prepare and test the actual adapter with dummy credentials before scarce runtime or short-lived grants begin. Use idempotent operations/durable intent and bounded work; no reset of prior costs or journals.

Covers: validate approved source bytes, dimensions and display; upload an approved candidate once, retain immutable provider identity, then use the supported canonical promotion with mirrored manifests/checksums/rights bindings. Candidate upload alone is not publication. Do not require a writable Git checkout inside the serving web container.

Reader: cleared source, sanitized content, complete chapters/TOC/boundaries, actual pagination/navigation and access checks. Draft import remains the default for an import-only task. A Reader-only release can proceed independently when audio is held.

Audio: reuse the title's approved provider/voice and accepted master/package. No default fallback provider or voice substitution. Apply current language campaign quality thresholds, no estimated alignment or fabricated scores. Require actual protected transport, playback/ending and accounting acceptance relevant to the changed path. No legacy MP3 shortcut for a verified chunked package.

## Release and recovery

Run applicable exact-head checks automatically; merge only that reviewed head and manually deploy exact merged main to changed services. Automatic deployments stay OFF. Stage/test before promotion where supported. Use existing authentication without exposing secrets. Deployment should preserve availability using supported provider behavior; do not introduce planned outages or custom installation machinery for ordinary publication. Reconcile uncertain outcomes read-only and preserve the existing rollback/history. A failed gate gets a narrow source correction and fresh applicable validation, not a waiver or blind provider rerun.

Activate only the exact title/artifacts whose gates pass. Verify customer-visible discovery, correct covers/text/audio, authenticated access, anonymous/expired denial and accurate usage/accounting where applicable. Do not mark LIVE from build success, candidate upload, canary or healthy service alone. Record service health and material limitations; never promise perfection, zero downtime or all conceivable fraud cases.

Use the current checkpoint for defect disposition. Open Window fractional-accounting and complete-usage-history corrections have retained deployed evidence; do not resurrect them as unresolved solely from an older note. Any newly reproduced accounting/access/publication defect remains a real hold until corrected and qualified. Do not remove checks or rewrite historical evidence to make a release appear unblocked.

## Communication

Continue routine authorized steps autonomously. Report material progress, a new failure, completion or one indispensable owner action; stay quiet on unchanged waits. Give a single next integration action. A local workflow update is not proof that production software or provider configuration changed.
