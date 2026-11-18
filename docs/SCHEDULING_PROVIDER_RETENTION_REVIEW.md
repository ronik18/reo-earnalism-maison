# Recurring operations and provider retention: activation package

19 November2026. **Owner approved the isolated Launch +7-day-log option; activation in progress.** Keep the existing$7 isolated web service, The Selfish Giant draft and all legacy/apex/DNS routes unchanged. Source/configuration can be tested/deployed without activating new billable runners.

## Actual provider readback

- Actual Neon organization inventory contains only thisoneproject andonecompute endpoint across its branches; organization-wide plan changes are therefore scoped to the observed Maison-only inventory. Recheck immediately before activation.
- Render workspace `earnalism`: Hobby, one member; current isolated web service0.5CPU/512MiB. Native application-log retention is7days. No recurring Maison service is configured.
- Neon organization `org-misty-dew-00335964`: Free. Project `quiet-cloud-63128335`: Singapore, PostgreSQL18, actual restore history21600seconds(6hours). Current endpoint min0.25/max2CU, suspend_timeout_seconds0 (provider default300seconds), not the approved production capacity.
- Approved production contract remains NeonScale min0.5/max2CU, autosuspendoff and7-day restore history. App2–6replica/HA acceptance is separate from this existing single-instance qualification service; this package does not claim it.
- Existing R2 content/public buckets and purge credentials remain untouched. Backup needs its own private bucket and credential; the old local backup profile uses an owner role and must not be promoted to the scheduled backup identity.
- Support destination is unset; Contact has an approved mailto fallback. No resolved support cases or automated mailbox purge is established. SMTP submission is not resolution, and this change will not apply organization-wide mailbox rules.

## Minimal proposed activation

| Resource | Exact change | Cost/authority boundary |
|---|---|---|
| Maintenance | One new Singapore Render Docker Starter cron, `* * * * *`, existing CI-approved source, autodeployoff, `python manage.py run_maintenance --apply-retention --run-source scheduled --max-seconds 45 --batch-size 25` | At least$1/month, $0.00016/minute for the0.5CPU/512MiB cron SKU prorated by active seconds, plus applicable tax/usage. Continuous30-day running would be$6.912 for this SKU; actual bounded job runtime determines billing. The minimum is not a cap. Copy only required existing Maison app/SMTP/privateR2/purge settings into its encrypted environment; no DNS/admin/publicasset-upload access. |
| Database | Upgrade existing Neon organization to Scale; set endpoint0.5–2CU, autosuspendoff and history7days, preserving database/roles/data | At current$0.222/CUh:360CUh/30days×$0.222=$79.92 compute floor; continuous2CU=$319.68. Add$0.35/GB-month DB storage and$0.20/GB-month history, plus applicable usage/taxes. Autoscaling spend depends on actual load. Free100CUh cannot support a fullmonth of constant minute polling even at0.25CU. |
| Independent export | Separate Singapore Docker Starter cron at03:00UTC; `python -m operations.scheduled_export --apply-retention`; no webapp startup/SMTP/ageprivateidentity | At least another$1/month plus active-second usage. Preserve the approved independent export lane instead of placing exports behind email work. Standalone entrypoint is proposed explicitly to avoid copying full webapp secrets into backups. |
| Private archive | Dedicated `reo-earnalism-maison-backups` R2 Standard private bucket, archive-only object read/write token, separate direct read-only DB role, public age recipient on export host | No new logging/storage vendor. R2 existing allowance is shared, not guaranteedfree: storage beyond free allowance$0.015/GB-month, request usage applies. About30daily+12monthly full encrypted snapshots after steady state; actualbytes determine cost. No manuscript/content/static prefix or existing lifecycle-rule mutation. |
| Key custody | Generate production age identity into an ignored mode600 owner-held local custody file, back it up privately via owner-chosen recovery custody; send only public recipient to Render | Private restore identity never goes to Render/R2/GitHub/chat. Do not reuse synthetic qualification identities. New scoped credential access needs explicit approval before creation/transmission. |

Illustrative quiet qualification total on a30-day month: existingweb$7 + Neonminimum$79.92 + two cronminimums$2 = **$88.92 before storage/history/runtime/tax**. This is not a hardbudget or production HA quote. A one-minute poll defeats normal5-minute autosuspend; do not advertise idle scale-to-zero savings while that poll is enabled. Read actual cron instance rate and selected provider plan before activation; do not accept a higher tier or workspace upgrade under this estimate.

## Optional isolated-qualification exception, not production-baseline conformity

The owner may explicitly choose NeonLaunch at the already qualified current0.25–2CU range, with7-day history and the same PostgreSQL/driver/regions/archive architecture, instead of activating the productionScale/min0.5CU baseline now. This changes the plan/minimum-capacity acceptance for isolated qualification only; production SLA/capacity/HA are not certified by it. The owner explicitly approved this isolated exception on19November2026; actual provider application/readback is tracked separately.

At currentLaunch$0.106/CUh, continuousminimum0.25CU×720hours costs$19.08/30days; continuous2CU costs$152.64, plus storage/history/tax. Existingweb$7 + minimumtwo cron$2 gives an illustrative **$28.08 quiet30-day floor** before runtime/storage/history/tax, not a hardcap. Minute polling still prevents normal idle scale-to-zero. Source and existing isolated browser/database acceptance already run on0.25CU; this is not a substitute for provider-plan activation/load/recovery acceptance. The approved productionScale0.5–2CU baseline remains intact unless separately amended.

## Log-retention choice requiring explicit owner decision

The approved ordinary-log window is30days. Native Render retention is Hobby7days, Pro14days, Scale/Enterprise30days. Current RenderScale workspace/organization price is$499/month, before compute; Pro does not supply30days. Do not upgrade just to satisfy a checkbox.

**Economical recommendation for this isolated scope:** explicitly amend ordinary provider-log retention to the existing native7days, while retaining90-day eligible application security outcomes and the separately approved backup schedule. The owner explicitly approved this isolated7-day exception on19November2026; existing nativeHobby retention already provides7days.

If30-day log lookback remains required, choose a separately approved nativeScale upgrade or review a Maison-only encrypted archive adapter. The latter requires additional Render API access/new retained log destination, scope review, gap detection/redaction and actual automatic archive evidence; no broad API key or collector is silently introduced. No existing authorized log sink has been verified.

## Exact mail-copy boundary for review

The approved seven-day material window names server action tokens and mail-job payloads. It does not establish a mailbox-wide deletion rule. The application uses stable exact `Message-ID` correlation, but no sender-mailbox read/delete access or automatic Sent retention is established by SMTP qualification. Recipient-controlled copies are outside Maison's deletion authority.

No global Google Workspace/Vault/mailbox rule will be changed. Support-form delivery is currently unset and no resolved-case provider cleanup has been qualified; mailto correspondence remains in the existing Reo business-mail process. The proposed smallest scope is to keep those mailbox copies under the separately recorded operator/business-mail policy, without claiming automated erasure or an empty mailbox. If the owner includes sender Sent/support-mailbox copies in automated retention, explicit exact-Maison-only mailbox access and an eligible-copy reconciliation are required before that item is complete; unrelated Reo/legacy mail must be excluded.

## Before activation and actual acceptance

1. Test/review/push and deploy only the safe application/configuration changes to the existing isolated service. No new cron is started merely by committing its Blueprint.
2. Inspect current due outbox categories and scheduled revisions before minute maintenance is enabled. Preserve this draft; do not create pending SMTP/publication fixtures in production. Current maintenance does not execute scheduled publication; that full-P0 gap remains separately tracked and cannot be claimed qualified by installing cron.
3. After explicit spending/access/policy approval, provision only the exact accepted resources, read back settings and encrypted environment names, and verify isolated domain/legacy/book state.
4. Observe a provider-caused automatic minute occurrence plus its durable UUID/start/end/source/outcome/lastsuccess receipt. Manual TriggerRun alone is not automatic-schedule evidence. Test overlap/busy/expiry/failure and then recovery without disclosing payloads.
5. Observe a genuine03:00UTC scheduled encrypted export, private R2 upload and SHA readback. Download/decrypt/restore in an approved isolated local target; compare actual table/content hashes. No claim that byte transfer alone establishes restoreability.
6. Qualify daily30days/exactlatest12monthly cleanup with generated-prefix validation, pair verification and holds; test malformed/missing pairs and unrelatedkey exclusion. No blanket native expiry rule can override a hold. Scheduling/log/support/mailbox/restore-history readbacks each stay distinct in the consolidated checklist.

## Official sources checked19November2026

- [Render cron billing and single-run behavior](https://render.com/docs/cronjobs)
- [Render log-retention plans](https://render.com/docs/logging#retention-period)
- [Render workspace features](https://render.com/docs/platform-features-by-plan), [pricing](https://render.com/pricing)
- [Cloudflare R2 pricing](https://developers.cloudflare.com/r2/pricing/)
- [Neon current pricing](https://neon.com/pricing), [history-window semantics](https://github.com/neondatabase/website/blob/main/content/docs/postgres/backup-restore/history-window.md)
- [Neon suspend field specification](https://github.com/neondatabase/neon-api-python/blob/main/v2.json)

No resource, plan, credential, native retention rule, public DNS or legacy deployment has been changed by preparing this package.

## Prepared source qualification

55 affected tests pass against PostgreSQL18 and bounded transport fixtures: routine audit/support resolution/holds/ownership, concurrent maintenance lease expiry/completion, immutable archive readback, daily/monthly/orphan retention, corrupt/missing references and unrelatedkey preservation. Both prepared RenderBlueprints pass the official schema SHA256 `6c6721a602ef6d368d5c9384c473cefaae99980e43dd4b1adcf8a2f258fc54f4`. No new dependency, database migration or public API is introduced. These tests do not substitute for the automatic provider trigger, actual backup upload/restore, mailbox authority or paid-plan acceptance.

## Safe rollout completed before activation approval

Implementation source `77901394188da771e92d5bf4baf3e176cb08135b` passed [exact-source CI44388432433](https://github.com/ronik18/reo-earnalism-maison/actions/runs/44388432433):294backend tests,28frontend tests, build and migration/no-drift checks. It is normal-pushed to main and deployed Live to the existing$7 isolated webservice (`dep-dbv0fjjrjlhs73agjt30`), staticreleaseunchanged.7/7 independent HTTPS checks pass. Fresh directNeon read-only verification preserves draft/nullpointer/32paragraphs/manuscriptSHA and shows no dueoutbox, scheduledrevisions or supportcases. No recurring run is claimed: maintenance receipt count0.

[Actual deployed/read-only receipt](evidence/provider-retention-safe-deployment.json), [independent HTTPS receipt](evidence/provider-retention-independent-smoke.json). The owner has now explicitly approved the isolatedLaunch package, scoped backup access and7-daylog exception. Activation and actual provider acceptance remain in progress; business mail stays operator-managed. No additional spending, DNS or legacy changes occurred.
