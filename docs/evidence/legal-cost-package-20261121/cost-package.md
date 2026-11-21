# HA / PITR / load — exact proposed authorization package

21November2026; source93b9730. **PREPARED / NOT APPROVED / NOT EXECUTED.** All amounts are USD. The exact proposed authorization is a **$50 gross additional-charge ceiling**, not a vendor quote or provider-enforced hard stop. [Actual account pricing](account-pricing-readback.json) confirms the underlying rates; taxes, subscription cessation and final synthetic-project disposition must pass the checks below before any purchase. The book stays draft; legacy/DNS are outside scope.

## One recommended finite pilot

| Authorized action proposed | Hard scope / return state |
|---|---|
| Existing Render workspace Hobby→Pro | Budget one full$25billing cycle, not an assumed two-hour workspace fee. Keep existing$7compute tier. Use2–6replicas only for≤2hours; restore one instance afterward and Hobby by the end of the one paid cycle, only after that exact account-supported cessation route is verified. No duplicate webservice or Performance builds. |
| Existing Neon organization | **Keep Launch** and max2CU/seven-day history. Temporarily use0.5CUminimum during the two load profiles; return0.25CU/five-minute scale-to-zero afterward. No Scale purchase in this pilot. This is a proposed isolated-test exception, not an amendment or acceptance of the full production baseline. |
| One synthetic PITR target | Create exactly one separateSingapore/PostgreSQL18Launchproject/root, max2CU,≤2activecompute hours,≤1GBdata+≤1GBhistory,≤7daysretention. No Maison/book/customer data copied. Establish supported project/automatic-backup disposition and applicable deletion authority **before creation**; otherwise do not create it. Never restore the live production root. |
| Load | Same qualified image/static release and the [bounded workload](../neon-cap-followup-20261121/resilience.md): two13-minute5→50→5RPSprofiles,≤12260requests,256MiBresponse bytes,1500syntheticwrites,10adultsynthetic users,24HTTPconcurrency;48only in the declared rolling-overlap segment within the same aggregate budget. Proposed latency bounds are not approvedSLOs. |
| Recovery and alert | One synthetic own-history rootPITR and marker/schema/count/hash/readiness checks; one supported rolling/rollback action and one synthetic alert to an explicitly approved existing operator destination. No unplanned-failure claim from manual scaling. No payments,email,publication,uploads,newmedia,child activation or DNS. |
| Stop and return | Stop on the workload's errors/saturation limits, duration/byte/write cap or projected$50gross exposure. Stop load at2hours regardless of results, restore test settings, verify health/book/legacy and capture usage. No unidentified residual root/storage or future renewal is authorized. A spending notification alone cannot enforce this budget. |

### Exact reserve arithmetic

| Additional-cost reserve | Calculation | USD |
|---|---|---:|
| Pro workspace | One full cycle |25.00|
| Six existing-tier webinstances for2h |6×7×2/730,roundedup |0.12|
| Existing Launch endpoint for2h |2CU×2h×0.106,roundedup |0.43|
| Synthetic Launch endpoint for2h |2CU×2h×0.106,roundedup |0.43|
| Extra data/history for7days |(1GB×0.35+1GB×0.20)×7/30,roundedup |0.13|
| Network reserve |≤1GBbillable EACH at Render0.15+Neon0.10 |0.25|
| **Pre-tax resource reserve** | |**26.36**|
| **Proposed gross authorization ceiling** |Includes tax/fees/contingency; no extra services |**50.00**|

Compute is prorated by provider accounting; the730-hour arithmetic is a conservative planning convention, not a statement of the invoice calendar. Existing ordinary web/cron/R2/Stream/pre-pilot charges continue under their existing approvals and are not bought again here. Public asset caches are reused. Any new billed build, extra project, higher tier or new service is outside scope. The$23.64headroom is a reserve, not a promise of the final tax-inclusive bill. The UI's delayed$20Neonspend notification is advisory, not a hard cap.

### Three finite pre-execution conditions

1. Verify the binding Render amount/period, taxes/fees, renewal and exact one-cycle downgrade effective timing. The signed-in page confirms$25flat+compute,25GBbandwidth/$0.15perGBafter and1000buildminutes, but exposes no final tax/proration figure before the possibly binding Selectplan action. Do not click it without approval; do not infer its effect from its label.
2. Verify one synthetic project's supported creation/own-history restore/disposition and≤7dayresidual lifetime, including any automatic backup. If deletion is irreversible, obtain its required action-time confirmation. Do not create first and negotiate cleanup later. Resolve the allowed method before any compute/storage commitment.
3. Bind the exact execution window, synthetic fixture/cohort, proposed latency/stop limits, supported rolling action and existing alert destination. Confirm the full new exposure including tax fits$50; if not, stop before commitment and re-quote only the changed item. No load has run and no spend is approved by this document.

This pilot can qualify bounded current-isolated-stack behavior, observed autoscaling extent and a synthetic nativePITR mechanism. **It cannot certify the approved full Scale production topology, actual Maison-history restoration, all HA failure modes or productionSLO/RPO/RTO.** Failure to trigger sixinstances is inconclusive; do not silently increase load. The full HLD/LLD baseline remains binding.

## Native PITR: avoid a misleading cheap drill

Current [Neon restore documentation](https://neon.com/docs/postgres/backup-restore/branch-restore) distinguishes rootPITR from child reset and logicalrestore; restoration overwrites the target and interrupts connections. Cross-root restoration creates an automatic old-target backup root that normal branch deletion cannot remove. Snapshot-restored branches have a documentedPITR limitation. The [object model](https://neon.com/docs/concepts/the-object-model) says normal additional branches are children. Therefore an arbitrary same-project “disposable root” and a two-hour zero-residual bill are not established.

The proposed synthetic project's **own-history** rehearsal avoids production mutation and copying private data, but still needs verified residual/disposition treatment. Read-only TimeTravel may check Maison-history facts but is not a restore. Actual production-history recovery remains OPEN until its supported target/retained-backup construction, lifetime, cost, permissions and reconciliation are separately accepted. Do not call the synthetic pilot a production recovery pass.

## Separate full-production recurring decision — outside the pilot

If the owner chooses full-baseline qualification/continued operation instead, prepare a separate proposed **$500gross per730-hour cycle ceiling**, not a silent extension of the$50pilot. Baseline: RenderPro+samecompute2–6replicas/65%CPU and NeonScale0.5–2CU/autosuspendoff, seven-day history. Scale is organization-wide; the signed-in organization currently contains oneproject. No Scope/plan change is made here.

- At2webinstances except one≤2hour6instancewindow, Pro+web is$39.08/cycle. One continually activeScaleendpoint adds$81.03–$324.12compute; combined **$120.11–$363.20** before storage/history/transfer/tax and existingcron/R2/Stream.
- At6webinstances for the whole cycle, Pro+web+Scalecompute is **$148.03–$391.12**, same exclusions. Autoscaling cost follows observed instance/CU time, not a fixed$230database bill.
- TwoScaleendpoints at2CUeach for2hours cost at most$1.776compute alone, **not the total recurring bill**. Data$0.35/GB-month/history$0.20 must include every retained target/backup.

The recurring$500is a proposed owner budget, not a measured invoice, selected plan or providerhardcap. Before asking to execute, include the actual lifetime/storage/usage/tax and plan-effective-date facts and confirm the worst permitted configuration fits it. Otherwise quote the excess rather than using the ceiling as permission for unknown spending. Retaining Launch for the isolated pilot does not replace the approved fullScalebaseline.

## Verified primary pricing references

[Render pricing](https://render.com/pricing), [compute billing FAQ](https://render.com/docs/faq), [scaling](https://render.com/docs/scaling), [flat-fee workspace notice](https://render.com/changelog/updated-plans-for-render-workspaces), [Neon pricing](https://neon.com/pricing), [Neon plan model](https://github.com/neondatabase/website/blob/main/content/docs/introduction/plans.md), [Neon billing](https://neon.com/docs/introduction/manage-billing). Launch$0.106/CUh;Scale$0.222/CUh. Account readback verifies500GBincludedNeonnetwork/project, one38.31MBproject and19.21MBhistory. Published rates and current usage do not supply missing final tax, cancellation or recovery-disposition terms.
