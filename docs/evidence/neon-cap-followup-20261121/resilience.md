# Resilience follow-up: concrete bounded drill proposal

21 November 2026, main `831f06e`. **Prepared, not executed; production HA/native PITR/capacity remain unqualified.** Root owns the separately approved Neon maximum correction to2CU and its post-save/readiness receipt. This lane makes no provider, database, runtime, DNS or spending change. It does not operate another lane's containers. Existing logical-restore, private-media and health evidence is reused rather than repeated.

## Smallest workload package

The retained HLD/LLD requires matching the hosting-model workload, but the checked repository does not establish a complete numeric RPS/mix/route-latency acceptance budget. The following is a **bounded proposal for review**, not an approved production SLO, measured capacity or replacement for the hosting model. It supplies a concrete starting point instead of waiting on an undefined “load test.”

Use one explicitly approved isolated test application/database target, exact merged image/static release, synthetic bilingual metadata and10adult synthetic users. Do not include The Selfish Giant or customer accounts. No payments, publication, support/email delivery, uploads or entitlement mutations. Preauthenticate the synthetic sessions outside timed measurements. Test content must have local synthetic rights and no publicly discoverable release.

Run the same profile once at the approved full baseline minimum0.5CU and once with2CUmaximum; retain provider-observed CU, not just requested bounds. Keep the actual current isolated0.25CUminimum distinct. Each profile:

| Stage | Duration | Fixed offered rate | Request bound |
|---|---:|---:|---:|
| Steady baseline |300s|5requests/s|1500|
| Tenfold burst |60s|50requests/s|3000|
| Recovery |300s|5requests/s|1500|
| Cooldown |120s|1request/s|120|

Two profiles total12240requests plus at most20explicit readiness/preflight requests: **12260HTTP requests**,26minutes timed load. Cap concurrent HTTP requests at24, using48only in an independently scheduled rolling-overlap segment with the same total request/byte budget. This cap is not a claim of24active database-query capacity. At50RPS with24concurrent requests, record unsent/dropped iterations honestly if response times cannot sustain offered rate; do not queue without bound. No live load is run now.

Proposed route mix:40%catalog list/search (including bounded pagination),20%synthetic title/Reader metadata,20%private synthetic Reader package grants/reads,10%synthetic progress/preference updates,10%private synthetic audio64KiBRange reads. Count every grant and subsequent media request within the total; predeclare URLs/IDs and exclude external provider Stream minutes. Limit aggregate downloaded application/media bytes to256MiB and total changed synthetic application records to1500; no data/rights creation inside timed loops. Limit origin cache-cold setup to the synthetic fixture keys; no zone-wide purge. Use previously qualified CDN behavior rather than load the legacy/apex.

Measure offered/completed/dropped throughput, route-by-route p50/p95/p99,errors,CPU/RAM,actual instance count,CU/query/pool/lock latency,connections and bidirectional bytes. Record2→6→2replicas and rolling overlap only if they actually occur under the approved autoscaling configuration; failure to reach6within the rate/time budget is an inconclusive scaling extent, not permission to increase load. Do not fabricate node failure by manual2→1scaling: it does not prove unplanned failover.

**Proposed acceptance for review:** zero unauthorized data access or correctness failures; no lost/duplicated acknowledged synthetic writes; steady-state application p95≤1000ms/p99≤2500ms and request errors<1%, with route/region separation. These latency numbers are proposals, not approved source requirements. Preserve the existing contract's pool-wait p95≤250ms and configured query/connect bounds as alert signals. Stop immediately on any cross-account/rights/legacy request, any charge/publication/email, or a correctness failure; stop the active stage if5xx exceed1%over a rolling minute with at least50requests, a DB timeout repeats3times, the provider exceeds the approved2CU/6instance limits,256MiB/12260requests/1500writes are reached, or the approved elapsed/spend cap is hit. Never stop the actual application or its scheduler as a budget response.

## Native PITR: correct non-destructive target semantics

Current official [Neon instant-restore documentation](https://neon.com/docs/postgres/backup-restore/branch-restore) supports root-to-root PITR; a normal child reset is a different operation. Restoring overwrites target data/schema and interrupts its connections. Therefore **do not restore production and do not call a child reset PITR**. Prepare a provider-supported separate disposable root recovery target only after its exact creation/restore/retained-backup method, count, cost and final disposition are approved. Snapshot-created branches currently have a documented PITR limitation; do not select that shortcut without checking the actual method.

Choose a timestamp inside the readback-verified actual history; verify known canary/state before and after it without modifying the source. Match schema/migrations,table counts/content hashes and referenced private-object identities; reconcile accounts/revocation/retention as already specified. Measure from operator trigger to validated target readiness. Retain the actual source/target/time and provider result; no restoration is attempted here. Seven-day configuration is neither seven elapsed days nor a successful recovery. Keep five-minute node,ten-minute zonal,four-hour regional and24hour independent-export RPO labels untested until the corresponding actual drills pass.

## Consolidated cost/action package: priced components, not a fabricated all-in quote

Primary documentation checked today: [Render scaling](https://render.com/docs/scaling), [Render workspace plan change](https://render.com/changelog/updated-plans-for-render-workspaces), [Render pricing](https://render.com/pricing), [Neon pricing](https://neon.com/pricing). Current source claims are preserved; no paid plan is silently downgraded/replaced. Render autoscaling requires Pro or higher, separate from per-replica compute. The existing dashboard receipt establishes the selected0.5CPU/512MB service price$7/month; source docs establish Pro$25/month plus compute. Neon publishes Launch$0.106/CU-hour and Scale$0.222/CU-hour. Actual account checkout/tax/proration must be read before approval.

| Exact prospective action | Bounded component calculation | Exclusions / approval condition |
|---|---|---|
| Existing Render workspace Pro; same service2–6instances, same compute plan |$25/month workspace plus$14–$42/month web compute while retained; combined$39–$67/month before other resources |Increment over current$7web is$32–$60/month. This is not an isolated two-hour all-in charge; workspace subscription/renewal and proration must be explicit. Existing cron,bandwidth,tax excluded. No duplicate web service proposed.|
| Two-hour web drill at maximum6replicas |At730hmonthly arithmetic,6×$7×2/730≈$0.115web compute; additional five vs currentone≈$0.096 |Informational estimate only; actual vendor billing granularity and extra traffic apply. No cap is enforced merely by arithmetic.|
| Approved full Neon Scale0.5–2CU baseline |At730h,$81.03–$324.12/month compute for one continuously running endpoint; actual CU average matters |Not the current Launch cost. Data/history/extra root or branch storage and network excluded. Switching plan requires exact approval; retaining Launch forPITR-only would require explicit baseline amendment if used instead of the approved full topology.|
| Two-hour Scale drill plus separate recovery endpoint, each capped2CU |At most8CU-hours×$0.222=$1.776endpoint compute if both exist for the same two-hour window |Additional target/retained-backup storage,possible extra branches,history,traffic,tax excluded; no target is created. Source plus target and retained-backup identities must be priced.|
| Storage/history |Neon data$0.35/GB-month;history$0.20/GB-month |Use actual retained sizes and target delta; do not infer a zero total from current small source size.|

**This is not yet an exact total spend authorization package.** The remaining finite inputs are account-applicable Pro checkout/proration/renewal, Render traffic/compute billing and existing service charges, Neon plan-change treatment plus the selected recovery-root/backup/storage lifetime, taxes and bounded egress. Root can read those without accepting terms or saving settings, then present one total and cap. Do not ask the owner to approve an open-ended “do all HA tests” or claim$1.776is the full drill bill. Source workload/latency proposal needs root reconciliation with the original hosting model before running.

The safe immediate outcome is the approved2CUcap restoration/readiness receipt plus this concrete test/cost proposal. Actual autoscaling,HA,PITR,alert delivery and public capacity remain OPEN. No new monitoring/cache/queue/provider is introduced; use existing provider metrics and existing operator channel when its exact test action is approved.
