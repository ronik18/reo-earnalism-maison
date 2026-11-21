# Isolated guardian schema migration — approval package preparation

21 November 2026. **Approval-ready schema scope; execution remains conditional on final application tests passing.** Source schema is frozen, historical-data rehearsal passed, and exact hashes are in [migration-manifest.json](migration-manifest.json). Nothing has been applied. This supersedes neither the earlier migration exclusion nor the required exact approval. Schema deployment does not qualify or activate child processing.

## Exact existing target

- Existing Neon project `quiet-cloud-63128335`, production branch `br-nameless-rain-aok6bsea`, database `neondb`, Singapore; PostgreSQL18.7.
- Direct endpoint `ep-wispy-wildflower-aotla8gh.c-2.ap-southeast-1.aws.neon.tech`, TLS certificate verification required. Existing scoped credential stays in memory; no URL/password in repository or output.
- Fresh read-only inspection: accounts migrations0001_initial,0002_mfa_recovery_code,0003_allauth_email_authority; guardian table absent. Owner default table/sequence privileges already grant SELECT to `maison_backup`; verify the actual migration role is that owner and the resulting new-table SELECT before claiming archive acceptance.
- Protected edition55a3f5e3-f713-40b2-a873-942cd97bb1b7 / revision3988156b-2eee-4839-b542-2d3b8b253307 must remain draft/null live/version42/32paragraphs/hash8431612b87bf77f609c4f2f6944d185fa7ea69709b10d6be259e85f27c8165d4. Finance inventory remains empty. No legacy/database/DNS/title change.

## Proposed tightly scoped action

Apply exactly accounts.0004_guardian_authorization_foundation and accounts.0005_guardianauthorization_claim_expires_at_and_more, plus Django's corresponding content-type/permission bookkeeping, after final tests pass. New relations affect account cleanup even when the feature is off, so schema must precede deployment. Do not deploy model code first. Do not run broad unreviewed pending migrations. No backfill of child records, reviewer grants, policy enablement, age restriction, foreign route or automatic guardian rights action is included.

Use an explicit direct connection and local lock/statement timeout for the migration transaction. Creation/foreign-key validation may briefly lock referenced auth_user and other schema objects; do not describe it as zero-lock or guarantee no latency. Timeout or an unexpected plan/state/target aborts rather than applying a partial guessed migration. Check atomicity of each final migration and avoid external operations within its transaction.

## Rehearsal and verification required

1. Record final migration file and emitted SQL SHA256; inspect dependencies and forward/reverse SQL. Rehearse forward/idempotent repeat and application rollback on separate local PostgreSQL18 synthetic data, including real existing-user deletion/untouched-signup cleanup, permission/default-privilege and backup-reader acceptance. A local rehearsal is not a Neon branch acceptance claim. No additional paid branch is provisioned.
2. Recheck exact live migration inventory, server/database/credential target and book/finance invariants read-only immediately before an approved action. Verify a current successful encrypted archive/restore receipt; do not turn an old recovery drill into a new backup.
3. Apply only the exact approved migration target. Afterward verify constraints, migration rows, correct owner and backup-reader SELECT, no unexpected data, and protected invariants. If SELECT is absent, stop and present the exact new-table-only grant; do not silently broaden role privileges.
4. Deploy only the tested source/static candidate to the existing isolated web/maintenance/archive services, with guardian activation and production policies still off unless separately qualified/approved. Validate actual account deletion/cleanup compatibility using authorized synthetic fixtures, current admin/account navigation, API boundaries, ordinary reader behavior, cron lease outcomes and immutable assets.
5. Keep new feature OFF and use compatible application rollback as the normal recovery. Dropping new tables may destroy authority/claim records once used; no destructive down-migration is preapproved. If no records exist and removal becomes necessary, present the exact reverse plan separately. Book/legacy recovery is not part of this additive schema change.

## Approval boundary

The eventual question must identify the exact migration filenames, source/SQL hashes, target and tested operation. It authorizes only that schema action and isolated deployment—not public/all-ages legal clearance, appointments, filings, provider spend, title publication, legacy cutover, new age/country restrictions or physical UAT. Any additional provider or public activation approval remains separate and concrete.

## Frozen changes and actual rehearsal

0004 creates maison_guardian_authorization with its foreign keys/checks/indexes and review permission. 0005 adds auth_user.guardian_managed defaultFalse (existing accounts remain ordinary), adds the nullable claim/retention fields and unique random prospective subject UUID, and makes child binding nullable. The historical-data RunPython generates a different UUID for each existing grant; this operation cannot be represented by sqlmigrate alone. SQL snapshots include generated temporary UUID defaults that may differ per emission; **the authoritative execution approval is the two exact migration source hashes**, not executing these SQL snapshots by hand.

[Local PostgreSQL18 historical-data rehearsal](migration-rehearsal.json) passed with two pre-existing grant rows: distinct per-row UUID backfill, existing users unchanged/unmanaged, repeat plan empty, child cascade and reviewer SET_NULL, and prior model read compatibility. No down-migration or production clone was claimed. Full schema source/SQL is reviewable in the linked manifest and snapshots. An ALTER on auth_user requires a brief exclusive schema lock; set lock_timeout3seconds and statement_timeout30seconds, abort on unexpected target/plan/role/book state. Each migration is atomic; if0005 fails after0004 commits, keep the compatible additive table and old application, report the exact partial state, and do not deploy incomplete model code.

Normal application rollback to7297a9d is allowed only while production feature/policies stayed off **and no guardian-managed accounts or grants were created**. Once such accounts exist, an older application ignoring guardian authority can be unsafe; keep a compatible enforcing build and prepare a specific recovery plan. No automatic table/column drop or data deletion is approved by this package.

Approved execution would keep GUARDIAN_AUTHORIZATION_ENABLED=False and GUARDIAN_AUTHORIZATION_POLICIES={}. It would add no methods, child accounts or reviewer permission assignments. Public legal qualification remains separate; the deployed technical foundation must not be advertised as available parental verification.
