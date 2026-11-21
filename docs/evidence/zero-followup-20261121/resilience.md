# Zero-cost changed-area resilience validation

21 November 2026. **PASS: 10 focused tests, 0 failures/errors/skips, 23.727 seconds.** [Actual receipt](receipt.json). This is current-source local PostgreSQL authority/retention/concurrency acceptance, not cloud HA, a load-capacity claim or native PITR.

## Why this slice was run

The earlier 900-request workload and 71-table encrypted logical recovery used source `74a48e8`, before the owner-approved India-first enrollment changes. Repeating those unchanged bulk exercises would not directly validate the new permission lifetime, delayed-verification, renewal and cleanup rules. This pass instead exercises their existing targeted tests on exact current main `125e48e34866eeced6f413adf7f60272f8e3c20d`.

| Behavior actually checked | Result |
|---|---|
| Missing/tampered actual permission proof denies authority | PASS |
| Active permission proof survives classified audit cleanup; tampered binding fails | PASS |
| Delayed real mailbox-verification event cannot revive expired or unbound permission | PASS |
| Renewal binds the exact existing unverified child without duplicating the account | PASS |
| Expired unverified claim scaffolding is cleaned only after its retention conditions | PASS |
| Account deletion ends indefinite authority; evidence cleanup respects holds | PASS |
| Independent-capacity transition preserves the same account and ends former guardian power | PASS |
| Mailbox verification followed by withdrawal revokes managed sessions/devices | PASS |
| Two simultaneous claims produce one bound child, with the competing claim denied | PASS |
| Locked staff review rechecks revoked permission rather than trusting a stale precheck | PASS |

The tests simulate stale/delayed authority conditions and real PostgreSQL locking. They do not perform a physical restore; the delayed-event result is not relabelled production post-restore recovery evidence. Existing encrypted logical restore, workload and process-restart receipts remain reusable within their original scopes.

## Execution and custody

- Current checkout mounted **read-only** at `/app`; existing `earnalism-maison:india-followup-20261121` supplies installed dependencies only. Image ID is retained in the JSON receipt.
- Existing local PostgreSQL 18.7 container/network namespace reused. Django created only uniquely named `test_maison_zero_followup_resilience_20261121`; its normal teardown removed that test database, and the preexisting `maison` database remained present.
- Only synthetic test accounts/content and test-client requests. No real book, live account, provider credential, deployment, SMTP/OAuth/provider API, external load, download or hosted CI was used.
- An ephemeral runner container and tmpfs directories supplied writable test state; the source remained read-only. The runner container was removed. A private local test log/runner remains under ignored `.local`; only sanitized results and runner hash are included here.

**New provider spend: $0.** No application source, schema migration file, live configuration, DNS, book or legacy change was made. The $50 pilot remains declined. Native cloud PITR, Render HA/autoscaling, cloud capacity, full RPO/RTO and legal/title clearance keep their separately stated outstanding acceptance and spending-authority boundaries.
